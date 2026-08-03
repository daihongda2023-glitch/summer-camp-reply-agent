# 微信半自动辅助交互 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 WeFlow 监听到工作台、工作台辅助粘贴到微信输入框、运营确认发送日志的半自动交互闭环。

**Architecture:** 新增微信桥接配置/状态、WeFlow 增量监听器、辅助粘贴适配器，并把这些能力挂到现有浏览器版 `WorkbenchWebState` 和本地 Web API。发送边界严格保持“只复制/粘贴，不按 Enter，不点击发送”，只有运营点击“我已发送”后才记录为确认发送。

**Tech Stack:** Python 标准库、`unittest`、`http.server`、`ctypes` Win32 API、现有 WeFlow 导入器、现有工作台会话和 JSONL 存储。

---

## 文件结构

- 新建 `summer_camp_agent/wechat_bridge_config.py`：微信桥接配置、监听状态和 JSON 存储。
- 新建 `summer_camp_agent/wechat_live_listener.py`：WeFlow 增量监听器，把 WeFlow 消息转换为 `ChatEvent`。
- 新建 `summer_camp_agent/wechat_assisted_paste.py`：剪贴板与前台窗口辅助粘贴适配器。
- 修改 `summer_camp_agent/workbench_session.py`：增加可区分粘贴、确认发送的审计记录方法。
- 修改 `summer_camp_agent/workbench_web.py`：增加配置、监听、粘贴、确认发送 API 和 UI 按钮。
- 修改 `.gitignore`：忽略 `data/wechat_bridge_config.json`。
- 修改 `docs/README.md`：增加微信半自动辅助交互启动与安全边界说明。
- 新增 `tests/test_wechat_bridge_config.py`。
- 新增 `tests/test_wechat_live_listener.py`。
- 新增 `tests/test_wechat_assisted_paste.py`。
- 修改 `tests/test_workbench_session.py`。
- 修改 `tests/test_workbench_web.py`。

## 安全不变量

所有任务都必须保持以下不变量：

- 代码中不得调用 Enter、Return、发送按钮点击或鼠标点击。
- 粘贴动作只能由用户点击工作台按钮触发。
- 监听只连接 `127.0.0.1` 或 `localhost` 的 WeFlow API。
- Token 只从环境变量读取，不写入配置、日志或测试样例。
- `confirm-sent` 前不能把动作记录成已发送。
- 聊天记录不进入事实 RAG，只作为触发输入。

## Task 1: 微信桥接配置与监听状态

**Files:**
- Modify: `.gitignore`
- Create: `summer_camp_agent/wechat_bridge_config.py`
- Test: `tests/test_wechat_bridge_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wechat_bridge_config.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.wechat_bridge_config import (
    ListenerState,
    ListenerStateStore,
    WeChatBridgeConfig,
    WeChatBridgeConfigError,
    WeChatBridgeConfigStore,
)


class WeChatBridgeConfigTest(unittest.TestCase):
    def test_config_from_dict_rejects_remote_base_url(self):
        with self.assertRaisesRegex(WeChatBridgeConfigError, "只允许连接本机"):
            WeChatBridgeConfig.from_dict({"base_url": "https://example.com", "group_name": "测试群"})

    def test_config_store_round_trips_without_token_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wechat_bridge_config.json"
            store = WeChatBridgeConfigStore(path)
            config = WeChatBridgeConfig(
                base_url="http://127.0.0.1:5031",
                token_env="WEFLOW_API_TOKEN",
                group_name="测试群",
                session_id="",
                keywords=["报名", "住宿"],
                poll_interval_seconds=5,
                enabled=True,
            )

            store.save(config)
            loaded = store.load()
            raw = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(loaded.group_name, "测试群")
        self.assertEqual(loaded.keywords, ["报名", "住宿"])
        self.assertNotIn("token", json.dumps(raw, ensure_ascii=False).lower().replace("token_env", ""))

    def test_listener_state_store_hashes_session_and_caps_seen_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listener_state.json"
            store = ListenerStateStore(path, max_seen_ids=3)
            state = ListenerState.empty()
            state = state.with_seen_event("sha256:1")
            state = state.with_seen_event("sha256:2")
            state = state.with_seen_event("sha256:3")
            state = state.with_seen_event("sha256:4")
            state = state.with_session_id("room@chatroom")

            store.save(state)
            loaded = store.load()
            raw_text = path.read_text(encoding="utf-8")

        self.assertEqual(loaded.seen_event_ids, ["sha256:2", "sha256:3", "sha256:4"])
        self.assertTrue(loaded.session_id_hash.startswith("sha256:"))
        self.assertNotIn("room@chatroom", raw_text)

    def test_gitignore_covers_wechat_bridge_config(self):
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"

        self.assertIn("data/wechat_bridge_config.json", gitignore.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -B -m unittest tests.test_wechat_bridge_config
```

Expected: FAIL with `ModuleNotFoundError: No module named 'summer_camp_agent.wechat_bridge_config'`.

- [ ] **Step 3: Add `.gitignore` rule**

Append to `.gitignore` near other local data files:

```gitignore
data/wechat_bridge_config.json
```

- [ ] **Step 4: Implement minimal config and state store**

Create `summer_camp_agent/wechat_bridge_config.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .chat_log_sanitizer import hash_identifier


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "wechat_bridge_config.json"
DEFAULT_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "listener_state.json"


class WeChatBridgeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class WeChatBridgeConfig:
    base_url: str = "http://127.0.0.1:5031"
    token_env: str = "WEFLOW_API_TOKEN"
    group_name: str = ""
    session_id: str = ""
    keywords: list[str] = field(default_factory=lambda: ["报名", "报到", "住宿", "交通", "作业", "面试", "GPU", "算子"])
    poll_interval_seconds: int = 5
    enabled: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WeChatBridgeConfig":
        config = cls(
            base_url=str(raw.get("base_url") or "http://127.0.0.1:5031"),
            token_env=str(raw.get("token_env") or "WEFLOW_API_TOKEN"),
            group_name=str(raw.get("group_name") or ""),
            session_id=str(raw.get("session_id") or ""),
            keywords=[str(item).strip() for item in raw.get("keywords", []) if str(item).strip()],
            poll_interval_seconds=int(raw.get("poll_interval_seconds") or 5),
            enabled=bool(raw.get("enabled", True)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise WeChatBridgeConfigError("WeFlow base_url 只允许连接本机 127.0.0.1 或 localhost。")
        if self.poll_interval_seconds < 2 or self.poll_interval_seconds > 60:
            raise WeChatBridgeConfigError("poll_interval_seconds 必须在 2 到 60 秒之间。")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class ListenerState:
    session_id_hash: str = ""
    last_poll_at: str = ""
    last_message_time: str = ""
    seen_event_ids: list[str] = field(default_factory=list)
    consecutive_errors: int = 0

    @classmethod
    def empty(cls) -> "ListenerState":
        return cls()

    @classmethod
    def from_dict(cls, raw: dict[str, Any], max_seen_ids: int = 2000) -> "ListenerState":
        return cls(
            session_id_hash=str(raw.get("session_id_hash") or ""),
            last_poll_at=str(raw.get("last_poll_at") or ""),
            last_message_time=str(raw.get("last_message_time") or ""),
            seen_event_ids=[str(item) for item in raw.get("seen_event_ids", [])][-max_seen_ids:],
            consecutive_errors=int(raw.get("consecutive_errors") or 0),
        )

    def with_session_id(self, session_id: str) -> "ListenerState":
        return ListenerState(
            session_id_hash=hash_identifier(session_id),
            last_poll_at=self.last_poll_at,
            last_message_time=self.last_message_time,
            seen_event_ids=[*self.seen_event_ids],
            consecutive_errors=self.consecutive_errors,
        )

    def with_seen_event(self, event_id: str, max_seen_ids: int = 2000) -> "ListenerState":
        seen = [item for item in self.seen_event_ids if item != event_id]
        seen.append(event_id)
        return ListenerState(
            session_id_hash=self.session_id_hash,
            last_poll_at=datetime.now(timezone.utc).isoformat(),
            last_message_time=self.last_message_time,
            seen_event_ids=seen[-max_seen_ids:],
            consecutive_errors=0,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WeChatBridgeConfigStore:
    def __init__(self, path: str | Path = DEFAULT_CONFIG_PATH):
        self.path = Path(path)

    def load(self) -> WeChatBridgeConfig:
        if not self.path.exists():
            return WeChatBridgeConfig()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise WeChatBridgeConfigError("微信桥接配置必须是 JSON 对象。")
        return WeChatBridgeConfig.from_dict(raw)

    def save(self, config: WeChatBridgeConfig) -> None:
        config.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


class ListenerStateStore:
    def __init__(self, path: str | Path = DEFAULT_STATE_PATH, max_seen_ids: int = 2000):
        self.path = Path(path)
        self.max_seen_ids = max_seen_ids

    def load(self) -> ListenerState:
        if not self.path.exists():
            return ListenerState.empty()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return ListenerState.empty()
        return ListenerState.from_dict(raw, self.max_seen_ids)

    def save(self, state: ListenerState) -> None:
        capped = ListenerState.from_dict(state.to_dict(), self.max_seen_ids)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(capped.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
python -B -m unittest tests.test_wechat_bridge_config
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add .gitignore summer_camp_agent/wechat_bridge_config.py tests/test_wechat_bridge_config.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: add wechat bridge config store"
```

## Task 2: WeFlow 增量监听器

**Files:**
- Create: `summer_camp_agent/wechat_live_listener.py`
- Test: `tests/test_wechat_live_listener.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wechat_live_listener.py`:

```python
import unittest

from summer_camp_agent.wechat_bridge_config import ListenerStateStore, WeChatBridgeConfig
from summer_camp_agent.wechat_live_listener import WeFlowLiveListener
from summer_camp_agent.weflow_import import WeFlowSession


class FakeClient:
    def __init__(self):
        self.search_calls = []
        self.pull_calls = []

    def search_sessions(self, keyword):
        self.search_calls.append(keyword)
        return [WeFlowSession(id="room@chatroom", name="测试群", type="group")]

    def pull_messages(self, session_id, *, since, end, limit, offset):
        self.pull_calls.append((session_id, since, end, limit, offset))
        return {
            "meta": {"groupId": "room@chatroom"},
            "messages": [
                {
                    "sender": "wxid_a",
                    "timestamp": 1781911260,
                    "type": 0,
                    "content": "报名入口在哪里？",
                    "platformMessageId": "msg-1",
                },
                {
                    "sender": "wxid_b",
                    "timestamp": 1781911320,
                    "type": 0,
                    "content": "收到，谢谢老师",
                    "platformMessageId": "msg-2",
                },
            ],
            "sync": {"hasMore": False},
        }


class MemoryStateStore(ListenerStateStore):
    def __init__(self):
        self.state = None

    def load(self):
        from summer_camp_agent.wechat_bridge_config import ListenerState

        return self.state or ListenerState.empty()

    def save(self, state):
        self.state = state


class WeFlowLiveListenerTest(unittest.TestCase):
    def test_poll_once_returns_new_chat_events_and_persists_seen_ids(self):
        store = MemoryStateStore()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(group_name="测试群", keywords=["报名"]),
            state_store=store,
            client=FakeClient(),
            token="fake-token",
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].content, "报名入口在哪里？")
        self.assertEqual(result.events[0].group_name, "测试群")
        self.assertIn(result.events[0].event_id, store.state.seen_event_ids)
        self.assertTrue(store.state.session_id_hash.startswith("sha256:"))

    def test_poll_once_filters_already_seen_events(self):
        store = MemoryStateStore()
        fake_client = FakeClient()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(group_name="测试群", keywords=["报名"]),
            state_store=store,
            client=fake_client,
            token="fake-token",
        )

        first = listener.poll_once()
        second = listener.poll_once()

        self.assertEqual(len(first.events), 1)
        self.assertEqual(second.events, [])
        self.assertEqual(second.status, "ok")

    def test_poll_once_reports_missing_token(self):
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(group_name="测试群", token_env="MISSING_WEFLOW_TOKEN"),
            state_store=MemoryStateStore(),
            client=FakeClient(),
            token="",
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "error")
        self.assertIn("缺少 MISSING_WEFLOW_TOKEN", result.message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -B -m unittest tests.test_wechat_live_listener
```

Expected: FAIL with `ModuleNotFoundError: No module named 'summer_camp_agent.wechat_live_listener'`.

- [ ] **Step 3: Implement live listener**

Create `summer_camp_agent/wechat_live_listener.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from typing import Any

from .chat_log_sanitizer import AliasRegistry, build_sanitized_message
from .wechat_bridge_config import ListenerStateStore, WeChatBridgeConfig
from .weflow_import import (
    WeFlowAuthError,
    WeFlowImportClient,
    WeFlowImportError,
    WeFlowSession,
    WeFlowSessionSelectionRequired,
)
from .workbench_models import ChatEvent


@dataclass(frozen=True)
class ListenerPollResult:
    status: str
    message: str
    events: list[ChatEvent]


class WeFlowLiveListener:
    def __init__(
        self,
        config: WeChatBridgeConfig,
        *,
        state_store: ListenerStateStore | None = None,
        client: Any | None = None,
        token: str | None = None,
    ):
        self.config = config
        self.state_store = state_store or ListenerStateStore()
        self.token = token
        self.client = client
        self.alias_registry = AliasRegistry()
        self._session: WeFlowSession | None = None

    def poll_once(self) -> ListenerPollResult:
        token_value = self.token if self.token is not None else os.environ.get(self.config.token_env, "")
        if not token_value:
            return ListenerPollResult("error", f"缺少 {self.config.token_env}，请先设置 WeFlow API Token 环境变量。", [])
        try:
            client = self.client or WeFlowImportClient(self.config.base_url, token_value)
            session = self._resolve_session(client)
            state = self.state_store.load().with_session_id(session.id)
            payload = client.pull_messages(session.id, since=None, end=None, limit=100, offset=0)
            events: list[ChatEvent] = []
            for raw in payload.get("messages", []):
                if not isinstance(raw, dict):
                    continue
                event = self._event_from_raw(raw, session)
                if event is None or event.event_id in state.seen_event_ids:
                    continue
                events.append(event)
                state = state.with_seen_event(event.event_id)
            self.state_store.save(state)
            return ListenerPollResult("ok", f"已拉取 {len(events)} 条新消息", events)
        except WeFlowSessionSelectionRequired:
            return ListenerPollResult("error", "找到多个匹配群聊，请使用 session_id 明确指定。", [])
        except WeFlowAuthError as exc:
            return ListenerPollResult("error", str(exc), [])
        except WeFlowImportError as exc:
            return ListenerPollResult("error", str(exc), [])

    def _resolve_session(self, client: Any) -> WeFlowSession:
        if self._session is not None:
            return self._session
        if self.config.session_id:
            self._session = WeFlowSession(self.config.session_id, self.config.group_name or self.config.session_id, "group")
            return self._session
        sessions = client.search_sessions(self.config.group_name)
        exact = [session for session in sessions if session.name == self.config.group_name]
        candidates = exact or sessions
        if len(candidates) != 1:
            raise WeFlowSessionSelectionRequired(candidates)
        self._session = candidates[0]
        return self._session

    def _event_from_raw(self, raw: dict[str, Any], session: WeFlowSession) -> ChatEvent | None:
        timestamp = int(raw.get("timestamp") or 0)
        message_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else ""
        message = build_sanitized_message(
            source="weflow_live",
            group_name=session.name,
            group_id=session.id,
            message_time=message_time,
            sender_id=str(raw.get("sender") or "unknown"),
            content=str(raw.get("content") or ""),
            keywords=self.config.keywords,
            platform_message_id=str(raw.get("platformMessageId") or raw.get("id") or timestamp),
            raw_type=raw.get("type", "text"),
            alias_registry=self.alias_registry,
            include_media=False,
        )
        if message is None:
            return None
        return ChatEvent(
            event_id=message.platform_message_id_hash,
            group_id_hash=message.group_id_hash,
            group_name=message.group_name,
            sender_alias=message.sender_alias,
            sender_role=message.sender_role,
            message_time=message.message_time,
            content=message.content,
            raw_type=str(message.raw_type),
            source=message.source,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -B -m unittest tests.test_wechat_live_listener
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add summer_camp_agent/wechat_live_listener.py tests/test_wechat_live_listener.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: add weflow live listener"
```

## Task 3: 工作台审计动作

**Files:**
- Modify: `summer_camp_agent/workbench_session.py`
- Test: `tests/test_workbench_session.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workbench_session.py`:

```python
    def test_record_operator_action_logs_paste_without_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent("evt-paste", "sha256:group", "夏令营咨询群", "成员001", "student", "2026-06-21 10:00:00", "报名入口在哪里？", "text", "manual")
            item = session.process_event(event)

            session.record_operator_action(item, item.review_card.reply, operator_action="pasted_to_wechat", action="paste")

            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("pasted_to_wechat", log_text)
            self.assertNotIn("operator_confirmed_sent", log_text)

    def test_confirm_operator_sent_saves_edited_candidate_and_confirmed_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent("evt-confirm", "sha256:group", "夏令营咨询群", "成员001", "student", "2026-06-21 10:00:00", "报名入口在哪里？", "text", "manual")
            item = session.process_event(event)

            session.confirm_operator_sent(item, "同学你好，报名入口请看官方链接。")

            self.assertIn("官方链接", (root / "candidates.jsonl").read_text(encoding="utf-8"))
            self.assertIn("edited_and_confirmed_sent", (root / "logs.jsonl").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -B -m unittest tests.test_workbench_session
```

Expected: FAIL with `AttributeError: 'WorkbenchSession' object has no attribute 'record_operator_action'`.

- [ ] **Step 3: Implement audit methods**

Modify `summer_camp_agent/workbench_session.py`:

```python
    def confirm_operator_sent(self, item: WorkbenchItem, edited_reply: str) -> None:
        reply = edited_reply.strip()
        if not reply:
            return
        operator_action = "edited_and_confirmed_sent" if reply != item.review_card.reply.strip() else "operator_confirmed_sent"
        if operator_action == "edited_and_confirmed_sent":
            self._append_candidate(item, reply, datetime.now(timezone.utc).isoformat())
        self.record_operator_action(item, reply, operator_action=operator_action, action="confirm_sent")

    def record_operator_action(
        self,
        item: WorkbenchItem,
        reply: str,
        *,
        operator_action: str,
        action: str,
    ) -> None:
        text = reply.strip()
        if not text:
            return
        now = datetime.now(timezone.utc).isoformat()
        self.log_store.append(
            ReplyLogEntry(
                log_id=hash_identifier(f"{item.event.event_id}:{text}:{operator_action}:{now}"),
                group_name=item.event.group_name,
                trigger_message_hash=hash_identifier(item.event.event_id),
                trigger_reasons=item.trigger.reasons,
                mode=item.reply_decision.mode,
                action=action,
                reply=text,
                source=item.review_card.source,
                confidence=item.review_card.confidence,
                operator_action=operator_action,
                created_at=now,
            )
        )
```

Keep existing `confirm_reply` behavior for the old MVP “发送” button.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -B -m unittest tests.test_workbench_session
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add summer_camp_agent/workbench_session.py tests/test_workbench_session.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: add workbench assisted send audit actions"
```

## Task 4: 辅助粘贴适配器

**Files:**
- Create: `summer_camp_agent/wechat_assisted_paste.py`
- Test: `tests/test_wechat_assisted_paste.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wechat_assisted_paste.py`:

```python
import inspect
import unittest

from summer_camp_agent.wechat_assisted_paste import AssistedPasteAdapter, PasteResult


class FakeBackend:
    def __init__(self, can_paste=True):
        self.can_paste = can_paste
        self.clipboard_text = ""
        self.shortcuts = []

    def set_clipboard_text(self, text):
        self.clipboard_text = text

    def foreground_window_title(self):
        return "微信"

    def send_ctrl_v(self):
        if not self.can_paste:
            raise OSError("paste failed")
        self.shortcuts.append("CTRL+V")


class WechatAssistedPasteTest(unittest.TestCase):
    def test_copy_only_rejects_empty_text(self):
        result = AssistedPasteAdapter(FakeBackend()).copy_only("   ")

        self.assertEqual(result.action, "failed")
        self.assertIn("不能为空", result.message)

    def test_copy_only_writes_clipboard_without_paste(self):
        backend = FakeBackend()

        result = AssistedPasteAdapter(backend).copy_only("同学你好")

        self.assertEqual(result.action, "copied")
        self.assertEqual(backend.clipboard_text, "同学你好")
        self.assertEqual(backend.shortcuts, [])

    def test_paste_to_foreground_uses_only_ctrl_v(self):
        backend = FakeBackend()

        result = AssistedPasteAdapter(backend).paste_to_foreground("同学你好")

        self.assertEqual(result.action, "pasted")
        self.assertEqual(backend.shortcuts, ["CTRL+V"])
        self.assertEqual(result.foreground_window_title, "微信")

    def test_paste_failure_downgrades_to_copied(self):
        backend = FakeBackend(can_paste=False)

        result = AssistedPasteAdapter(backend).paste_to_foreground("同学你好")

        self.assertEqual(result.action, "copied")
        self.assertIn("已复制到剪贴板", result.message)

    def test_module_does_not_send_enter_or_mouse_clicks(self):
        import summer_camp_agent.wechat_assisted_paste as module

        source = inspect.getsource(module).lower()

        self.assertNotIn("vk_return", source)
        self.assertNotIn("mouseevent", source)
        self.assertNotIn("leftdown", source)
        self.assertNotIn("leftup", source)
        self.assertIsInstance(PasteResult("copied", "ok"), PasteResult)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -B -m unittest tests.test_wechat_assisted_paste
```

Expected: FAIL with `ModuleNotFoundError: No module named 'summer_camp_agent.wechat_assisted_paste'`.

- [ ] **Step 3: Implement paste adapter**

Create `summer_camp_agent/wechat_assisted_paste.py`:

```python
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import sys


@dataclass(frozen=True)
class PasteResult:
    action: str
    message: str
    foreground_window_title: str = ""


class AssistedPasteAdapter:
    def __init__(self, backend=None):
        self.backend = backend or WindowsPasteBackend()

    def copy_only(self, text: str) -> PasteResult:
        value = text.strip()
        if not value:
            return PasteResult("failed", "回复内容不能为空。")
        try:
            self.backend.set_clipboard_text(value)
        except Exception as exc:  # noqa: BLE001
            return PasteResult("failed", f"写入剪贴板失败：{exc}")
        return PasteResult("copied", "已复制到剪贴板，请手动粘贴到微信输入框。")

    def paste_to_foreground(self, text: str) -> PasteResult:
        copied = self.copy_only(text)
        if copied.action != "copied":
            return copied
        title = ""
        try:
            title = self.backend.foreground_window_title()
            self.backend.send_ctrl_v()
            return PasteResult("pasted", "已填入当前前台窗口，请在微信中确认后手动发送。", title)
        except Exception:
            return PasteResult("copied", "已复制到剪贴板，但未能自动粘贴。请手动粘贴到微信输入框。", title)


class WindowsPasteBackend:
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_V = 0x56

    def __init__(self):
        self.user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        self.kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

    def set_clipboard_text(self, text: str) -> None:
        if sys.platform != "win32":
            raise OSError("当前平台不支持自动写入系统剪贴板")
        data = (text + "\0").encode("utf-16le")
        h_global = self.kernel32.GlobalAlloc(self.GMEM_MOVEABLE, len(data))
        if not h_global:
            raise OSError("GlobalAlloc failed")
        locked = self.kernel32.GlobalLock(h_global)
        if not locked:
            raise OSError("GlobalLock failed")
        ctypes.memmove(locked, data, len(data))
        self.kernel32.GlobalUnlock(h_global)
        if not self.user32.OpenClipboard(None):
            raise OSError("OpenClipboard failed")
        try:
            self.user32.EmptyClipboard()
            if not self.user32.SetClipboardData(self.CF_UNICODETEXT, h_global):
                raise OSError("SetClipboardData failed")
        finally:
            self.user32.CloseClipboard()

    def foreground_window_title(self) -> str:
        if sys.platform != "win32":
            return ""
        hwnd = self.user32.GetForegroundWindow()
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def send_ctrl_v(self) -> None:
        if sys.platform != "win32":
            raise OSError("当前平台不支持自动粘贴")
        self._key_down(self.VK_CONTROL)
        self._key_down(self.VK_V)
        self._key_up(self.VK_V)
        self._key_up(self.VK_CONTROL)

    def _key_down(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, 0, 0)

    def _key_up(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, self.KEYEVENTF_KEYUP, 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -B -m unittest tests.test_wechat_assisted_paste
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add summer_camp_agent/wechat_assisted_paste.py tests/test_wechat_assisted_paste.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: add safe wechat assisted paste adapter"
```

## Task 5: 工作台状态和 Web API 集成

**Files:**
- Modify: `summer_camp_agent/workbench_web.py`
- Test: `tests/test_workbench_web.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workbench_web.py`:

```python
class FakeListener:
    def __init__(self, events):
        self.events = events
        self.poll_count = 0

    def poll_once(self):
        from summer_camp_agent.wechat_live_listener import ListenerPollResult

        self.poll_count += 1
        return ListenerPollResult("ok", "ok", self.events)


class FakePasteAdapter:
    def __init__(self):
        self.pasted = []

    def paste_to_foreground(self, text):
        from summer_camp_agent.wechat_assisted_paste import PasteResult

        self.pasted.append(text)
        return PasteResult("pasted", "已填入当前前台窗口，请在微信中确认后手动发送。", "微信")


class WorkbenchWebWechatBridgeTest(unittest.TestCase):
    def test_poll_wechat_once_adds_listener_events_to_items(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent("evt-live", "sha256:group", "测试群", "成员001", "student", "2026-06-21 10:00:00", "报名入口在哪里？", "text", "weflow_live")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.wechat_listener = FakeListener([event])

            payload = state.poll_wechat_once()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["items"][0]["event_id"], "evt-live")

    def test_paste_reply_logs_paste_but_not_confirmed_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.paste_adapter = FakePasteAdapter()
            item = state.ask("报名入口在哪里？")["item"]

            result = state.paste_reply(item["event_id"], item["reply"])

            self.assertEqual(result["paste_action"], "pasted")
            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("pasted_to_wechat", log_text)
            self.assertNotIn("operator_confirmed_sent", log_text)

    def test_confirm_sent_records_operator_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            item = state.ask("报名入口在哪里？")["item"]

            result = state.confirm_sent(item["event_id"], item["reply"])

            self.assertEqual(result["status"], "ok")
            self.assertIn("operator_confirmed_sent", (root / "logs.jsonl").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -B -m unittest tests.test_workbench_web
```

Expected: FAIL with `AttributeError: 'WorkbenchWebState' object has no attribute 'poll_wechat_once'`.

- [ ] **Step 3: Implement state methods and routes**

Modify `summer_camp_agent/workbench_web.py`:

```python
from .wechat_assisted_paste import AssistedPasteAdapter
from .wechat_bridge_config import WeChatBridgeConfig, WeChatBridgeConfigStore
from .wechat_live_listener import WeFlowLiveListener
```

Extend `WorkbenchWebState.__init__`:

```python
        self.wechat_config = WeChatBridgeConfig()
        self.wechat_listener = None
        self.wechat_listener_running = False
        self.paste_adapter = AssistedPasteAdapter()
```

Add methods:

```python
    def configure_wechat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.wechat_config = WeChatBridgeConfig.from_dict(payload)
        WeChatBridgeConfigStore().save(self.wechat_config)
        return {"status": "ok", "message": "配置已保存", "config": self.wechat_config.to_dict()}

    def start_wechat_listener(self) -> dict[str, Any]:
        self.wechat_listener = WeFlowLiveListener(self.wechat_config)
        self.wechat_listener_running = True
        return {"status": "ok", "message": "已开始监听", "listener_state": {"running": True, "group_name": self.wechat_config.group_name}}

    def stop_wechat_listener(self) -> dict[str, Any]:
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
        action = "pasted_to_wechat" if result.action == "pasted" else "copied_to_clipboard" if result.action == "copied" else "paste_failed"
        self.session.record_operator_action(item, reply, operator_action=action, action="paste")
        return {"status": "ok", "paste_action": result.action, "message": result.message, "foreground_window_title": result.foreground_window_title}

    def confirm_sent(self, event_id: str, reply: str) -> dict[str, str]:
        item = self._find_item(event_id)
        self.session.confirm_operator_sent(item, reply)
        return {"status": "ok", "message": "已记录运营确认发送"}
```

Add routes in `do_POST`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -B -m unittest tests.test_workbench_web
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add summer_camp_agent/workbench_web.py tests/test_workbench_web.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: add wechat bridge web api"
```

## Task 6: 浏览器工作台 UI 接入微信交互按钮

**Files:**
- Modify: `summer_camp_agent/workbench_web.py`
- Test: `tests/test_workbench_web.py`

- [ ] **Step 1: Write the failing HTTP route test**

Append to `tests/test_workbench_web.py`:

```python
    def test_wechat_paste_route_returns_structured_result(self):
        from http.server import ThreadingHTTPServer
        import threading
        import urllib.request

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.paste_adapter = FakePasteAdapter()
            item = state.ask("报名入口在哪里？")["item"]
            server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/wechat/paste",
                    data=json.dumps({"event_id": item["event_id"], "reply": item["reply"]}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                payload = json.loads(urllib.request.urlopen(request, timeout=5).read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(payload["paste_action"], "pasted")
        self.assertIn("手动发送", payload["message"])
```

Also ensure the existing import line becomes:

```python
from summer_camp_agent.workbench_web import WorkbenchWebState, create_handler
```

- [ ] **Step 2: Run test to verify it fails or protects the route**

Run:

```powershell
python -B -m unittest tests.test_workbench_web
```

Expected before Task 5: FAIL with missing route. Expected after Task 5: PASS and protect the route.

- [ ] **Step 3: Update HTML controls**

Modify `WORKBENCH_HTML` in `summer_camp_agent/workbench_web.py`:

Add a WeFlow setup block inside `<aside class="left">` after group list:

```html
      <div class="bridge">
        <label>群聊名称</label>
        <input id="wechatGroupName" value="沐曦开源英才夏令营咨询群">
        <label>关键词</label>
        <input id="wechatKeywords" value="报名,报到,住宿,交通,作业,面试,GPU,算子">
        <label>轮询间隔</label>
        <input id="wechatPollSeconds" type="number" min="2" max="60" value="5">
      </div>
```

Add CSS:

```css
    .bridge {
      display: grid;
      gap: 6px;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
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
```

Replace left actions with:

```html
        <button onclick="saveWechatConfig()">保存监听配置</button>
        <button onclick="startWechatListener()">开始监听</button>
        <button onclick="pollWechatOnce()">拉取新消息</button>
        <button onclick="stopWechatListener()">停止监听</button>
        <button onclick="loadDemo()">载入演示</button>
        <button onclick="document.getElementById('jsonlFile').click()">导入 JSONL</button>
```

Add reply actions:

```html
        <button onclick="pasteToWechat()">填入微信</button>
        <button onclick="confirmSent()">我已发送</button>
```

Add JavaScript functions:

```javascript
    function readWechatConfig() {
      return {
        base_url: 'http://127.0.0.1:5031',
        token_env: 'WEFLOW_API_TOKEN',
        group_name: document.getElementById('wechatGroupName').value.trim(),
        session_id: '',
        keywords: document.getElementById('wechatKeywords').value.split(',').map(x => x.trim()).filter(Boolean),
        poll_interval_seconds: Number(document.getElementById('wechatPollSeconds').value || 5),
        enabled: true
      };
    }

    async function saveWechatConfig() {
      try {
        const data = await requestJson('/api/wechat/config', readWechatConfig());
        setStatus(data.message);
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function startWechatListener() {
      try {
        await saveWechatConfig();
        const data = await requestJson('/api/wechat/start', {});
        setStatus(data.message);
      } catch (error) {
        setStatus(error.message);
      }
    }

    async function stopWechatListener() {
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

    async function pasteToWechat() {
      if (!selectedId) {
        setStatus('请先选择一条消息。');
        return;
      }
      const reply = document.getElementById('replyBox').value.trim();
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
      try {
        const data = await requestJson('/api/wechat/confirm-sent', {event_id: selectedId, reply});
        setStatus(data.message);
      } catch (error) {
        setStatus(error.message);
      }
    }
```

- [ ] **Step 4: Run tests and HTTP smoke**

Run:

```powershell
python -B -m unittest tests.test_workbench_web
python -B -c "from http.server import ThreadingHTTPServer; import json, threading, urllib.request; from summer_camp_agent.workbench_web import WorkbenchWebState, create_handler; state=WorkbenchWebState(); server=ThreadingHTTPServer(('127.0.0.1', 0), create_handler(state)); port=server.server_address[1]; thread=threading.Thread(target=server.serve_forever, daemon=True); thread.start(); data=json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/demo', timeout=5).read().decode('utf-8')); print(len(data['items'])); server.shutdown(); server.server_close()"
```

Expected: tests PASS; smoke prints `5`.

- [ ] **Step 5: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add summer_camp_agent/workbench_web.py tests/test_workbench_web.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: add wechat assisted controls to workbench"
```

## Task 7: 文档与最终验证

**Files:**
- Modify: `docs/README.md`

- [ ] **Step 1: Update README**

Add this section to `docs/README.md` after “PC 端工作台 MVP 演示”:

```markdown
## 微信半自动辅助交互

工作台支持半自动接入普通微信群：

1. 手动启动 WeFlow，并在 WeFlow 设置中开启本地 API。
2. 在当前系统环境变量中设置 `WEFLOW_API_TOKEN`。
3. 双击 `启动夏令营Agent.cmd` 打开工作台。
4. 在左侧填写群聊名称、关键词和轮询间隔，点击“保存监听配置”。
5. 点击“开始监听”，再点击“拉取新消息”或保持工作台运行。
6. 工作台生成草稿后，先把光标放到目标微信群输入框，再点击“填入微信”。
7. 系统只会复制/粘贴，不会自动按回车或点击发送。
8. 在微信中人工确认并手动发送后，回到工作台点击“我已发送”。

该能力不会破解微信数据库，不注入微信客户端，不后台自动群发。若粘贴失败，工作台会降级为复制到剪贴板，请手动粘贴。
```

- [ ] **Step 2: Run full verification**

Run:

```powershell
python -B -m unittest discover -s tests
python -B -m py_compile summer_camp_agent/wechat_bridge_config.py summer_camp_agent/wechat_live_listener.py summer_camp_agent/wechat_assisted_paste.py summer_camp_agent/workbench_web.py
git diff --check
rg -n "sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{30,}|gh[p]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}" summer_camp_agent tests docs examples 启动夏令营Agent.cmd
```

Expected:

- All tests pass.
- `py_compile` exits 0.
- `git diff --check` exits 0.
- Secret scan prints no real secrets; exit code 1 is acceptable when there are no matches.

- [ ] **Step 3: Commit docs**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add docs/README.md
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "docs: explain wechat assisted interaction"
```

- [ ] **Step 4: Manual launch verification**

Run:

```powershell
cmd.exe /c start "" /D "D:\workspace\codex\自动回复agent" python -B -m summer_camp_agent.workbench_web
```

Then verify:

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/demo' -UseBasicParsing -TimeoutSec 5 | Select-Object StatusCode
```

Expected:

```text
StatusCode
----------
       200
```

## 最终报告

完成后汇报：

- 新增模块和职责。
- 新增 Web API。
- 微信交互安全边界。
- 验证命令和结果。
- 启动方式和手动演示步骤。
- 已知限制：依赖 WeFlow 本地 API；普通微信只做辅助粘贴，不自动发送。
