from __future__ import annotations

from datetime import datetime
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from typing import Any
from urllib.parse import urlparse
import webbrowser

from .chat_log_sanitizer import hash_identifier
from .wechat_assisted_paste import AssistedPasteAdapter
from .wechat_bridge_config import WeChatBridgeConfig, WeChatBridgeConfigStore
from .wechat_live_listener import WeFlowLiveListener
from .workbench_models import ChatEvent, GroupConfig
from .workbench_presenter import build_demo_events, format_item_summary, status_label
from .workbench_session import DEFAULT_CANDIDATE_PATH, DEFAULT_LOG_PATH, WorkbenchItem, WorkbenchSession
from .workbench_sources import load_events_from_jsonl_text


class WorkbenchWebState:
    def __init__(
        self,
        candidate_path: str | Path = DEFAULT_CANDIDATE_PATH,
        log_path: str | Path = DEFAULT_LOG_PATH,
        group_config: GroupConfig | None = None,
        wechat_config_path: str | Path | None = None,
    ):
        self.group_config = group_config or GroupConfig(group_name="夏令营咨询群", mode="semi_auto")
        self.session = WorkbenchSession(self.group_config, candidate_path=candidate_path, log_path=log_path)
        self.items: list[WorkbenchItem] = []
        self.wechat_config_store = WeChatBridgeConfigStore(wechat_config_path) if wechat_config_path else WeChatBridgeConfigStore()
        self.wechat_config = self.wechat_config_store.load()
        self.wechat_listener = None
        self.wechat_listener_running = False
        self.paste_adapter = AssistedPasteAdapter()

    def load_demo_items(self) -> dict[str, Any]:
        self.items = [self.session.process_event(event) for event in build_demo_events()]
        return self.list_items()

    def import_jsonl_text(self, text: str) -> dict[str, Any]:
        self.items = [self.session.process_event(event) for event in load_events_from_jsonl_text(text)]
        return self.list_items()

    def list_items(self) -> dict[str, Any]:
        return {"items": [serialize_item(item) for item in self.items]}

    def ask(self, question: str) -> dict[str, Any]:
        content = question.strip()
        if not content:
            raise ValueError("问题不能为空")
        event = ChatEvent(
            event_id=hash_identifier(f"{datetime.now().isoformat()}:{content}"),
            group_id_hash="sha256:web-manual",
            group_name=self.group_config.group_name,
            sender_alias="手动输入",
            sender_role="student",
            message_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            content=content,
            raw_type="text",
            source="web_manual",
        )
        item = self.session.process_event(event)
        self.items.append(item)
        return {"item": serialize_item(item), "items": [serialize_item(value) for value in self.items]}

    def send_reply(self, event_id: str, reply: str) -> dict[str, str]:
        item = self._find_item(event_id)
        self.session.confirm_reply(item, reply)
        return {"status": "ok", "message": "已记录发送动作"}

    def save_candidate(self, event_id: str, reply: str) -> dict[str, str]:
        item = self._find_item(event_id)
        if not self.session.save_candidate(item, reply):
            raise ValueError("候选回复不能为空")
        return {"status": "ok", "message": "已保存到待审核候选库"}

    def configure_wechat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.wechat_config = WeChatBridgeConfig.from_dict(payload)
        self.wechat_config_store.save(self.wechat_config)
        return {"status": "ok", "message": "配置已保存", "config": self.wechat_config.to_dict()}

    def get_wechat_config(self) -> dict[str, Any]:
        return {"config": self.wechat_config.to_dict()}

    def start_wechat_listener(self) -> dict[str, Any]:
        self.wechat_listener = WeFlowLiveListener(self.wechat_config)
        self.wechat_listener_running = True
        return {
            "status": "ok",
            "message": "已开始监听",
            "listener_state": {"running": True, "group_name": self.wechat_config.group_name},
        }

    def stop_wechat_listener(self) -> dict[str, str]:
        self.wechat_listener_running = False
        return {"status": "ok", "message": "已停止监听"}

    def poll_wechat_once(self) -> dict[str, Any]:
        if self.wechat_listener is None:
            return {"status": "error", "message": "请先开始监听", "items": [serialize_item(item) for item in self.items]}
        result = self.wechat_listener.poll_once()
        if result.status == "ok":
            for event in result.events:
                self.items.append(self.session.process_event(event))
        return {"status": result.status, "message": result.message, "items": [serialize_item(item) for item in self.items]}

    def paste_reply(self, event_id: str, reply: str) -> dict[str, str]:
        item = self._find_item(event_id)
        result = self.paste_adapter.paste_to_foreground(reply)
        operator_action = {
            "pasted": "pasted_to_wechat",
            "copied": "copied_to_clipboard",
        }.get(result.action, "paste_failed")
        self.session.record_operator_action(item, reply, operator_action=operator_action, action="paste")
        return {
            "status": "ok",
            "paste_action": result.action,
            "message": result.message,
            "foreground_window_title": result.foreground_window_title,
        }

    def confirm_sent(self, event_id: str, reply: str) -> dict[str, str]:
        item = self._find_item(event_id)
        self.session.confirm_operator_sent(item, reply)
        return {"status": "ok", "message": "已记录运营确认发送"}

    def _find_item(self, event_id: str) -> WorkbenchItem:
        for item in self.items:
            if item.event.event_id == event_id:
                return item
        raise ValueError("没有找到对应消息，请重新选择")


def serialize_item(item: WorkbenchItem) -> dict[str, Any]:
    return {
        "event_id": item.event.event_id,
        "group_name": item.event.group_name,
        "sender": item.event.sender_alias,
        "message_time": item.event.message_time,
        "question": item.event.content,
        "source": item.event.source,
        "summary": format_item_summary(item),
        "status": status_label(item),
        "mode": item.reply_decision.mode,
        "reply": item.reply_decision.reply,
        "trigger_reasons": item.trigger.reasons,
        "matched_keywords": item.trigger.matched_keywords,
        "recommendation": item.review_card.recommendation,
        "engine_action": item.review_card.action,
        "intent": item.review_card.intent,
        "answer_source": item.review_card.source,
        "confidence": item.review_card.confidence,
        "reason": item.reply_decision.reason or item.review_card.reason,
    }


def create_handler(state: WorkbenchWebState):
    class WorkbenchRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._send_html(WORKBENCH_HTML)
                return
            if path == "/api/demo":
                self._send_json(state.load_demo_items())
                return
            if path == "/api/items":
                self._send_json(state.list_items())
                return
            if path == "/api/wechat/config":
                self._send_json(state.get_wechat_config())
                return
            self._send_json({"error": "未找到接口"}, status=404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                payload = self._read_json()
                if path == "/api/ask":
                    self._send_json(state.ask(str(payload.get("question") or "")))
                    return
                if path == "/api/import-jsonl":
                    self._send_json(state.import_jsonl_text(str(payload.get("text") or "")))
                    return
                if path == "/api/send":
                    self._send_json(state.send_reply(str(payload.get("event_id") or ""), str(payload.get("reply") or "")))
                    return
                if path == "/api/save-candidate":
                    self._send_json(
                        state.save_candidate(str(payload.get("event_id") or ""), str(payload.get("reply") or ""))
                    )
                    return
                if path == "/api/wechat/config":
                    self._send_json(state.configure_wechat(payload))
                    return
                if path == "/api/wechat/start":
                    self._send_json(state.start_wechat_listener())
                    return
                if path == "/api/wechat/stop":
                    self._send_json(state.stop_wechat_listener())
                    return
                if path == "/api/wechat/poll":
                    self._send_json(state.poll_wechat_once())
                    return
                if path == "/api/wechat/paste":
                    self._send_json(state.paste_reply(str(payload.get("event_id") or ""), str(payload.get("reply") or "")))
                    return
                if path == "/api/wechat/confirm-sent":
                    self._send_json(state.confirm_sent(str(payload.get("event_id") or ""), str(payload.get("reply") or "")))
                    return
                self._send_json({"error": "未找到接口"}, status=404)
            except Exception as exc:  # noqa: BLE001 - local UI should surface friendly errors
                self._send_json({"error": str(exc)}, status=400)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("请求体必须是 JSON 对象")
            return value

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return WorkbenchRequestHandler


def find_free_port(preferred: int = 8765) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> None:
    port = find_free_port()
    state = WorkbenchWebState()
    server = ThreadingHTTPServer(("127.0.0.1", port), create_handler(state))
    url = f"http://127.0.0.1:{port}/"
    print(f"夏令营群聊答疑运营工作台已启动：{url}")
    webbrowser.open(url)
    server.serve_forever()


WORKBENCH_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>夏令营群聊答疑运营工作台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f6f7;
      --panel: #ffffff;
      --line: #d9dee5;
      --text: #17202a;
      --muted: #68717d;
      --green: #16833a;
      --green-soft: #eaf7ef;
      --amber: #8a5a00;
      --amber-soft: #fff7e2;
      --red: #a33a2b;
      --red-soft: #fff1ef;
      --blue-soft: #eef6ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 "Microsoft YaHei UI", "Segoe UI", sans-serif;
    }
    header {
      height: 52px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      border-bottom: 1px solid var(--line);
      background: #fbfbfc;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
    }
    .mode {
      color: var(--green);
      font-weight: 600;
    }
    main {
      height: calc(100vh - 52px);
      display: grid;
      grid-template-columns: 230px minmax(420px, 1fr) 360px;
      grid-template-rows: minmax(0, 1fr) auto 32px;
    }
    aside, section {
      min-width: 0;
      border-right: 1px solid var(--line);
      background: var(--panel);
    }
    .left {
      padding: 12px;
      background: #f0f2f4;
    }
    .left h2, .stream h2, .decision h2 {
      margin: 0 0 10px;
      font-size: 14px;
      font-weight: 700;
    }
    .group {
      padding: 10px;
      margin-bottom: 8px;
      border: 1px solid transparent;
      background: #fff;
    }
    .group.active {
      border-color: #b9d8c4;
      background: var(--green-soft);
    }
    .group small {
      display: block;
      color: var(--muted);
      margin-top: 2px;
    }
    .actions {
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }
    .bridge {
      display: grid;
      gap: 6px;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }
    .bridge[hidden] {
      display: none;
    }
    .bridge label {
      color: var(--muted);
      font-size: 12px;
    }
    .bridge input {
      width: 100%;
      border: 1px solid var(--line);
      padding: 7px 8px;
      font: inherit;
    }
    button, input[type="file"]::file-selector-button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      padding: 8px 10px;
      font: inherit;
      cursor: pointer;
    }
    button.primary {
      border-color: #137636;
      background: var(--green);
      color: #fff;
    }
    button:disabled {
      color: #9aa1aa;
      cursor: not-allowed;
      background: #f4f5f6;
    }
    .stream {
      grid-column: 2;
      grid-row: 1;
      display: flex;
      flex-direction: column;
      padding: 12px;
      overflow: hidden;
    }
    .messages {
      overflow: auto;
      border: 1px solid var(--line);
      background: #fff;
    }
    .message {
      width: 100%;
      display: block;
      text-align: left;
      border: 0;
      border-bottom: 1px solid #edf0f2;
      padding: 10px 12px;
      background: #fff;
    }
    .message:hover, .message.selected {
      background: var(--blue-soft);
    }
    .message .summary {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .status {
      display: inline-block;
      min-width: 54px;
      margin-right: 6px;
      font-size: 12px;
      color: var(--muted);
    }
    .待审核 .status { color: var(--green); }
    .转人工 .status { color: var(--red); }
    .待补充 .status { color: var(--amber); }
    .decision {
      grid-column: 3;
      grid-row: 1;
      padding: 12px;
      background: #fbfbfb;
      overflow: auto;
    }
    .kv {
      display: grid;
      grid-template-columns: 86px 1fr;
      gap: 8px 10px;
      padding: 10px 0;
      border-bottom: 1px solid #edf0f2;
    }
    .kv dt {
      color: var(--muted);
    }
    .kv dd {
      margin: 0;
      word-break: break-word;
    }
    .reply {
      grid-column: 1 / 4;
      grid-row: 2;
      display: grid;
      grid-template-rows: minmax(92px, 1fr) auto;
      gap: 8px;
      padding: 12px;
      min-height: 176px;
      border-top: 1px solid var(--line);
      background: #fff;
    }
    textarea {
      width: 100%;
      height: 100%;
      min-height: 92px;
      resize: none;
      border: 1px solid var(--line);
      padding: 10px;
      font: inherit;
    }
    .reply-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
      align-items: center;
    }
    .reply-actions button {
      min-width: 96px;
      min-height: 36px;
      white-space: nowrap;
    }
    .reply-actions button.primary {
      min-width: 112px;
    }
    .statusbar {
      grid-column: 1 / 4;
      grid-row: 3;
      padding: 6px 12px;
      color: var(--muted);
      border-top: 1px solid var(--line);
      background: #fbfbfc;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .upload {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }
    @media (max-width: 980px) {
      main {
        grid-template-columns: 190px minmax(320px, 1fr);
        grid-template-rows: minmax(0, 1fr) auto minmax(220px, 35vh);
      }
      .decision {
        grid-column: 1 / 3;
        grid-row: 3;
        border-top: 1px solid var(--line);
      }
      .reply {
        grid-column: 1 / 3;
        grid-row: 2;
      }
      .statusbar {
        display: none;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>夏令营群聊答疑运营工作台</h1>
    <div class="mode">半自动模式</div>
  </header>
  <main>
    <aside class="left">
      <h2>群聊</h2>
      <div class="group active">夏令营咨询群<small>监听演示中</small></div>
      <div class="group">入营通知群<small>待接入</small></div>
      <div class="group">技术答疑群<small>待接入</small></div>
      <div id="wechatDebugConfig" class="bridge" hidden>
        <label for="wechatGroupName">群聊名称</label>
        <input id="wechatGroupName" value="沐曦开源英才夏令营咨询群">
        <label for="wechatSessionId">Session ID</label>
        <input id="wechatSessionId" value="" placeholder="可选：直接指定 WeFlow session_id">
        <label for="wechatKeywords">关键词</label>
        <input id="wechatKeywords" value="报名,报到,住宿,交通,作业,面试,GPU,算子">
        <label for="wechatPollSeconds">轮询间隔</label>
        <input id="wechatPollSeconds" type="number" min="2" max="60" value="5">
      </div>
      <div class="actions">
        <button onclick="saveWechatConfig()">保存监听配置</button>
        <button onclick="startWechatListener()">开始监听</button>
        <button onclick="pollWechatOnce()">拉取新消息</button>
        <button onclick="stopWechatListener()">停止监听</button>
        <button onclick="loadDemo()">载入演示</button>
        <button onclick="document.getElementById('jsonlFile').click()">导入 JSONL</button>
      </div>
      <div class="upload">
        <input id="jsonlFile" type="file" accept=".jsonl,.txt" onchange="importJsonlFile()" hidden>
      </div>
    </aside>
    <section class="stream">
      <h2>消息流</h2>
      <div id="messages" class="messages"></div>
    </section>
    <section class="decision">
      <h2>决策面板</h2>
      <dl id="details" class="kv"></dl>
    </section>
    <section class="reply">
      <textarea id="replyBox" placeholder="选择消息后这里会自动填入草稿；也可以直接输入学生问题后点击生成草稿。"></textarea>
      <div class="reply-actions">
        <button onclick="askManual()">生成草稿</button>
        <button class="primary" onclick="pasteToWechat()">填入微信</button>
        <button onclick="confirmSent()">我已发送</button>
        <button onclick="sendReply()">记录发送</button>
        <button onclick="saveCandidate()">保存候选</button>
        <button onclick="copyReply()">复制</button>
      </div>
    </section>
    <div id="statusbar" class="statusbar">正在启动...</div>
  </main>
  <script>
    let items = [];
    let selectedId = null;
    let wechatPollTimer = null;
    let currentWechatConfig = {
      base_url: 'http://127.0.0.1:5031',
      token_env: 'WEFLOW_API_TOKEN',
      group_name: '',
      session_id: null,
      keywords: [],
      poll_interval_seconds: 5,
      enabled: true,
      show_debug_config: false
    };

    async function requestJson(path, body) {
      const options = body === undefined ? {} : {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      };
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '请求失败');
      return data;
    }

    function setStatus(text) {
      document.getElementById('statusbar').textContent = text;
    }

    function applyWechatConfig(config) {
      currentWechatConfig = {...currentWechatConfig, ...(config || {})};
      const debugConfig = document.getElementById('wechatDebugConfig');
      debugConfig.hidden = !currentWechatConfig.show_debug_config;
      document.getElementById('wechatGroupName').value = currentWechatConfig.group_name || '';
      document.getElementById('wechatSessionId').value = currentWechatConfig.session_id || '';
      document.getElementById('wechatKeywords').value = (currentWechatConfig.keywords || []).join(',');
      document.getElementById('wechatPollSeconds').value = currentWechatConfig.poll_interval_seconds || 5;
    }

    async function loadWechatConfig() {
      const data = await requestJson('/api/wechat/config');
      applyWechatConfig(data.config);
      return data.config;
    }

    function readWechatConfig() {
      const config = {...currentWechatConfig};
      if (config.show_debug_config) {
        config.group_name = document.getElementById('wechatGroupName').value.trim();
        config.session_id = document.getElementById('wechatSessionId').value.trim();
        config.keywords = document.getElementById('wechatKeywords').value.split(',').map(x => x.trim()).filter(Boolean);
        config.poll_interval_seconds = Number(document.getElementById('wechatPollSeconds').value || 5);
      }
      return config;
    }

    function normalizePollIntervalSeconds() {
      const source = currentWechatConfig.show_debug_config
        ? document.getElementById('wechatPollSeconds').value
        : currentWechatConfig.poll_interval_seconds;
      const raw = Number(source || 5);
      if (!Number.isFinite(raw)) return 5;
      return Math.max(2, Math.min(60, raw));
    }

    function clearWechatPolling() {
      if (wechatPollTimer) {
        window.clearInterval(wechatPollTimer);
        wechatPollTimer = null;
      }
    }

    function scheduleWechatPolling() {
      clearWechatPolling();
      const intervalMs = normalizePollIntervalSeconds() * 1000;
      wechatPollTimer = window.setInterval(() => {
        pollWechatOnce();
      }, intervalMs);
    }

    function renderItems(nextItems) {
      items = nextItems || [];
      const container = document.getElementById('messages');
      container.innerHTML = '';
      for (const item of items) {
        const button = document.createElement('button');
        button.className = `message ${item.status}`;
        button.dataset.id = item.event_id;
        button.onclick = () => selectItem(item.event_id);
        const status = document.createElement('span');
        status.className = 'status';
        status.textContent = item.status;
        const summary = document.createElement('span');
        summary.className = 'summary';
        summary.textContent = item.summary.replace(`[${item.status}] `, '');
        button.append(status, summary);
        container.appendChild(button);
      }
      if (items.length > 0) selectItem(items[0].event_id);
    }

    function selectItem(eventId) {
      selectedId = eventId;
      const item = items.find(value => value.event_id === eventId);
      if (!item) return;
      for (const node of document.querySelectorAll('.message')) {
        node.classList.toggle('selected', node.dataset.id === eventId);
      }
      document.getElementById('replyBox').value = item.reply || '';
      renderDetails(item);
      setStatus(`当前消息：${item.status}`);
    }

    const triggerReasonLabels = {
      keyword: '关键词命中',
      question_mark: '问号问题',
      mention: '被 @ 提及'
    };
    const recommendationLabels = {
      send: '建议发送',
      edit: '建议编辑',
      escalate: '转人工处理',
      mark_pending: '标记待补充',
      ignore: '忽略'
    };
    const engineActionLabels = {
      auto_reply: '自动回复',
      suggested_reply: '建议回复',
      human_fallback: '转人工处理',
      needs_info: '需要补充资料'
    };
    const intentLabels = {
      'registration.link': '报名入口',
      'selection.result': '录取结果',
      'cost.accommodation': '食宿费用',
      'technical.assignment': '技术作业',
      'rag.document': '资料库匹配'
    };

    function formatDecisionValue(value, labels, emptyText) {
      if (Array.isArray(value)) {
        if (!value.length) return emptyText;
        return value.map(item => labels[item] || item).join(', ');
      }
      if (!value) return emptyText;
      return labels[value] || value;
    }

    function renderDetails(item) {
      const rows = [
        ['学生问题', item.question],
        ['处理状态', item.status],
        ['触发原因', formatDecisionValue(item.trigger_reasons, triggerReasonLabels, '未触发')],
        ['命中关键词', item.matched_keywords.length ? item.matched_keywords.join(', ') : '无'],
        ['建议动作', formatDecisionValue(item.recommendation, recommendationLabels, '无')],
        ['引擎动作', formatDecisionValue(item.engine_action, engineActionLabels, '无')],
        ['意图', formatDecisionValue(item.intent, intentLabels, '未知')],
        ['来源', item.answer_source || '无'],
        ['置信度', Number(item.confidence || 0).toFixed(2)],
        ['模式决策', item.mode],
        ['原因', item.reason || '无']
      ];
      const details = document.getElementById('details');
      details.innerHTML = '';
      for (const [key, value] of rows) {
        const dt = document.createElement('dt');
        dt.textContent = key;
        const dd = document.createElement('dd');
        dd.textContent = value;
        details.append(dt, dd);
      }
    }

    async function loadDemo() {
      try {
        const data = await requestJson('/api/demo');
        renderItems(data.items);
        setStatus('已载入演示数据：包含可答复、转人工、待补充和未触发消息。');
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function importJsonlFile() {
      const input = document.getElementById('jsonlFile');
      const file = input.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = await requestJson('/api/import-jsonl', {text});
        renderItems(data.items);
        setStatus(`已导入 ${data.items.length} 条聊天记录：${file.name}`);
      } catch (error) {
        setStatus(error.message);
      } finally {
        input.value = '';
      }
    }

    async function saveWechatConfig() {
      try {
        const data = await requestJson('/api/wechat/config', readWechatConfig());
        applyWechatConfig(data.config);
        setStatus(data.message);
        return data;
      } catch (error) {
        setStatus(error.message);
        return null;
      }
    }

    async function startWechatListener() {
      try {
        const saved = await saveWechatConfig();
        if (!saved) return;
        const data = await requestJson('/api/wechat/start', {});
        setStatus(data.message);
        scheduleWechatPolling();
        await pollWechatOnce();
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function stopWechatListener() {
      clearWechatPolling();
      try {
        const data = await requestJson('/api/wechat/stop', {});
        setStatus(data.message);
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function pollWechatOnce() {
      try {
        const data = await requestJson('/api/wechat/poll', {});
        renderItems(data.items);
        setStatus(data.message);
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function askManual() {
      const question = document.getElementById('replyBox').value.trim();
      if (!question) {
        setStatus('请先在底部输入学生问题。');
        return;
      }
      try {
        const data = await requestJson('/api/ask', {question});
        renderItems(data.items);
        selectItem(data.item.event_id);
        setStatus('已生成草稿。');
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function sendReply() {
      if (!selectedId) {
        setStatus('请先选择一条消息。');
        return;
      }
      const reply = document.getElementById('replyBox').value.trim();
      if (!reply) {
        setStatus('回复内容不能为空。');
        return;
      }
      try {
        const data = await requestJson('/api/send', {event_id: selectedId, reply});
        setStatus(`${data.message}。普通微信阶段不执行隐藏式自动发送。`);
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function saveCandidate() {
      if (!selectedId) {
        setStatus('请先选择一条消息。');
        return;
      }
      const reply = document.getElementById('replyBox').value.trim();
      try {
        const data = await requestJson('/api/save-candidate', {event_id: selectedId, reply});
        setStatus(`${data.message}，未写入正式 FAQ。`);
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function pasteToWechat() {
      if (!selectedId) {
        setStatus('请先选择一条消息。');
        return;
      }
      const reply = document.getElementById('replyBox').value.trim();
      if (!reply) {
        setStatus('回复内容不能为空。');
        return;
      }
      const confirmed = window.confirm('请先把光标放到目标微信群输入框。本操作只粘贴，不会自动发送。继续吗？');
      if (!confirmed) return;
      try {
        const data = await requestJson('/api/wechat/paste', {event_id: selectedId, reply});
        setStatus(data.message);
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function confirmSent() {
      if (!selectedId) {
        setStatus('请先选择一条消息。');
        return;
      }
      const reply = document.getElementById('replyBox').value.trim();
      if (!reply) {
        setStatus('回复内容不能为空。');
        return;
      }
      try {
        const data = await requestJson('/api/wechat/confirm-sent', {event_id: selectedId, reply});
        setStatus(data.message);
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function copyReply() {
      const reply = document.getElementById('replyBox').value;
      if (!reply.trim()) {
        setStatus('回复内容为空。');
        return;
      }
      await navigator.clipboard.writeText(reply);
      setStatus('已复制回复内容。');
    }

    async function boot() {
      try {
        await loadWechatConfig();
      } catch (error) {
        setStatus(error.message);
      }
      await loadDemo();
    }

    window.addEventListener('DOMContentLoaded', boot);
    window.addEventListener('beforeunload', clearWechatPolling);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
