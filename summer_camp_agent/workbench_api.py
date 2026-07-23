from __future__ import annotations

from datetime import datetime
import inspect
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, RLock
from typing import Any
from urllib.parse import urlparse

from .chat_log_sanitizer import hash_identifier
from .desktop_settings import DesktopSettings, DesktopSettingsStore
from .wechat_assisted_paste import AssistedPasteAdapter
from .wechat_bridge_config import DEFAULT_GROUP_NAME, SEND_MODE_AUTO_SEND, WeChatBridgeConfig, WeChatBridgeConfigStore
from .wechat_live_listener import WeFlowLiveListener
from .wechat_vision import VisionState, WeChatVisionObserver
from .wechat_window import WindowsWeChatWindowBackend
from .weflow_import import WeFlowImportClient, WeFlowImportConfig, fetch_weflow_messages
from .workbench_models import ChatEvent, GroupConfig
from .workbench_presenter import build_demo_events, format_item_summary, status_label
from .work_trace import load_work_trace
from .workbench_session import DEFAULT_CANDIDATE_PATH, DEFAULT_LOG_PATH, DEFAULT_TRACE_PATH, WorkbenchItem, WorkbenchSession
from .workbench_sources import load_events_from_jsonl_text
from .workbench_store import WorkbenchInboxStore


DEFAULT_INBOX_PATH = Path(__file__).resolve().parents[1] / "data" / "workbench_inbox.jsonl"


class WorkbenchApiState:
    def __init__(
        self,
        candidate_path: str | Path = DEFAULT_CANDIDATE_PATH,
        log_path: str | Path = DEFAULT_LOG_PATH,
        trace_path: str | Path | None = None,
        inbox_path: str | Path | None = None,
        group_config: GroupConfig | None = None,
        wechat_config_path: str | Path | None = None,
        desktop_settings_path: str | Path | None = None,
        rag_answer_generator=None,
    ):
        self.group_config = group_config or GroupConfig(group_name=DEFAULT_GROUP_NAME, mode="semi_auto")
        self.trace_path = Path(trace_path) if trace_path is not None else self._default_trace_path(candidate_path)
        self.session = WorkbenchSession(
            self.group_config,
            candidate_path=candidate_path,
            log_path=log_path,
            trace_path=self.trace_path,
            rag_answer_generator=rag_answer_generator,
        )
        self.items: list[WorkbenchItem] = []
        isolated_data_root = Path(candidate_path).parent if Path(candidate_path) != DEFAULT_CANDIDATE_PATH else None
        resolved_wechat_config_path = (
            Path(wechat_config_path)
            if wechat_config_path is not None
            else (isolated_data_root / "wechat_bridge_config.json" if isolated_data_root is not None else None)
        )
        self.wechat_config_store = (
            WeChatBridgeConfigStore(resolved_wechat_config_path)
            if resolved_wechat_config_path is not None
            else WeChatBridgeConfigStore()
        )
        self.wechat_config = self.wechat_config_store.load()
        self._sync_group_config_from_wechat()
        resolved_inbox_path = (
            Path(inbox_path)
            if inbox_path is not None
            else (
                isolated_data_root / "workbench_inbox.jsonl"
                if isolated_data_root is not None
                else DEFAULT_INBOX_PATH
            )
        )
        self.inbox_store = WorkbenchInboxStore(resolved_inbox_path)
        self.items = [
            self.session.process_event(event)
            for event in self.inbox_store.load()
        ]
        self.wechat_listener = None
        self.wechat_listener_running = False
        self._poll_lock = RLock()
        self._publish_lock = Lock()
        self._replied_event_ids: set[str] = set()
        self.paste_adapter = AssistedPasteAdapter()
        resolved_desktop_settings_path = (
            Path(desktop_settings_path)
            if desktop_settings_path is not None
            else (isolated_data_root / "desktop_settings.json" if isolated_data_root is not None else None)
        )
        self.desktop_settings_store = (
            DesktopSettingsStore(resolved_desktop_settings_path)
            if resolved_desktop_settings_path is not None
            else DesktopSettingsStore()
        )
        self.desktop_settings = self.desktop_settings_store.load()
        self.app_running = False
        self.recent_logs: list[str] = []
        self.vision_observer = WeChatVisionObserver()
        self.vision_window_backend = WindowsWeChatWindowBackend()
        self.vision_window_title = "微信"

    def get_app_status(self) -> dict[str, Any]:
        return {
            "engine": {
                "status": "running" if self.app_running else "idle",
                "listener_running": self.wechat_listener_running,
                "group_name": self.wechat_config.group_name,
                "send_mode": self.wechat_config.send_mode,
                "poll_interval_seconds": self.wechat_config.poll_interval_seconds,
            },
            "settings": self.desktop_settings.to_dict(),
            "recent_logs": self.recent_logs[-20:],
        }

    def start_app(self) -> dict[str, Any]:
        self.app_running = True
        self.recent_logs.append("桌面控制器已启动")
        return self.get_app_status()

    def stop_app(self) -> dict[str, Any]:
        self.app_running = False
        self.wechat_listener_running = False
        self.recent_logs.append("桌面控制器已停止")
        return self.get_app_status()

    def get_app_settings(self) -> dict[str, Any]:
        self.desktop_settings = self.desktop_settings_store.load()
        return {
            "settings": self.desktop_settings.to_dict(),
            "wechat": self.wechat_config.to_dict(),
            "reply": {
                "mode": self.group_config.mode,
                "auto_reply_intents": self.group_config.auto_reply_intents,
                "daily_auto_reply_limit": self.group_config.daily_auto_reply_limit,
            },
        }

    def update_app_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = DesktopSettings.from_dict(payload)
        self.desktop_settings_store.save(settings)
        self.desktop_settings = settings
        if isinstance(payload.get("wechat"), dict):
            self.wechat_config = WeChatBridgeConfig.from_dict(payload["wechat"])
            self.wechat_config_store.save(self.wechat_config)
            self._sync_group_config_from_wechat()
            self._refresh_wechat_listener_if_running()
            self._reprocess_items()
        if isinstance(payload.get("reply"), dict):
            reply = payload["reply"]
            self._set_group_config(
                GroupConfig(
                    group_name=self.group_config.group_name,
                    group_id_hash=self.group_config.group_id_hash,
                    enabled=self.group_config.enabled,
                    mode=str(reply.get("mode") or self.group_config.mode),
                    keywords=[*self.group_config.keywords],
                    agent_mentions=[*self.group_config.agent_mentions],
                    auto_reply_intents=[
                        str(item).strip()
                        for item in reply.get("auto_reply_intents", self.group_config.auto_reply_intents)
                        if str(item).strip()
                    ],
                    daily_auto_reply_limit=int(reply.get("daily_auto_reply_limit") or self.group_config.daily_auto_reply_limit),
                )
            )
        self.recent_logs.append("桌面设置已保存")
        return self.get_app_settings()

    def load_demo_items(self) -> dict[str, Any]:
        self.items = [self.session.process_event(event) for event in build_demo_events()]
        return self.list_items()

    def import_jsonl_text(self, text: str) -> dict[str, Any]:
        self.items = [self.session.process_event(event) for event in load_events_from_jsonl_text(text)]
        return self.list_items()

    def import_weflow_group(
        self,
        group_name: str,
        *,
        client: WeFlowImportClient | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        active_group_name = group_name.strip()
        if not active_group_name:
            raise ValueError("群聊名称不能为空")
        config = WeFlowImportConfig(
            group_name=active_group_name,
            keywords=[],
            limit=5000,
            base_url=self.wechat_config.base_url,
            token_env=self.wechat_config.token_env,
        )
        fetched = fetch_weflow_messages(config, client=client, token=token)
        self._set_group_config(
            GroupConfig(
                group_name=fetched.group_name,
                group_id_hash=self.group_config.group_id_hash,
                enabled=self.group_config.enabled,
                mode=self.group_config.mode,
                keywords=[*self.group_config.keywords],
                agent_mentions=[*self.group_config.agent_mentions],
                auto_reply_intents=[*self.group_config.auto_reply_intents],
                daily_auto_reply_limit=self.group_config.daily_auto_reply_limit,
            )
        )
        self.items = [
            self.session.process_event(
                ChatEvent(
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
            )
            for message in fetched.messages
        ]
        return {
            "status": "ok",
            "message": f"已从 WeFlow 导入 {len(self.items)} 条聊天记录：{fetched.group_name}",
            "items": self._serialize_items(),
        }

    def list_items(self) -> dict[str, Any]:
        if self.wechat_listener_running and self.wechat_listener is not None:
            self._poll_wechat_listener()
        return {"items": self._serialize_items()}

    def list_work_trace(self) -> dict[str, Any]:
        rows = load_work_trace(self.trace_path)
        event_ids = {item.event.event_id for item in self.items}
        active_rows = [row for row in rows if not event_ids or str(row.get("event_id") or "") in event_ids]
        return {
            "trace": active_rows,
            "summary": {
                "total": len(active_rows),
                "observed": sum(1 for row in active_rows if row.get("phase") == "observe"),
                "thought": sum(1 for row in active_rows if row.get("phase") == "think"),
                "acted": sum(1 for row in active_rows if row.get("phase") == "act"),
            },
        }

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
        return {"item": self._serialize_item(item), "items": self._serialize_items()}

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
        self._sync_group_config_from_wechat()
        self._refresh_wechat_listener_if_running()
        self._reprocess_items()
        return {
            "status": "ok",
            "message": "配置已保存",
            "config": self.wechat_config.to_dict(),
            "items": self._serialize_items(),
        }

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
        with self._poll_lock:
            if self.wechat_listener is None:
                return {"status": "error", "message": "请先开始监听", "items": self._serialize_items()}
            result = self._call_wechat_listener(include_seen=True)
            if result.status == "ok":
                self._append_listener_events(result.events)
            return {"status": result.status, "message": result.message, "items": self._serialize_items()}

    def paste_reply(self, event_id: str, reply: str) -> dict[str, str]:
        item = self._find_item(event_id)
        action = "paste"
        paste_method = getattr(self.paste_adapter, "paste_to_wechat_foreground", self.paste_adapter.paste_to_foreground)
        result = self._call_paste_method(paste_method, reply)
        operator_action = self._operator_action_for_paste_result(result)
        self.session.record_operator_action(item, reply, operator_action=operator_action, action=action)
        return self._paste_result_payload(result)

    def publish_reply(self, event_id: str, reply: str) -> dict[str, str]:
        if self.wechat_config.send_mode != SEND_MODE_AUTO_SEND:
            raise ValueError("请先在配置中选择系统自动发送，再使用自动发布。")
        with self._poll_lock:
            with self._publish_lock:
                item = self._find_item(event_id)
                if self._is_event_replied(item.event.event_id):
                    raise ValueError("该消息已回复，已阻止重复发送。")
                publish_method = getattr(self.paste_adapter, "send_to_wechat_foreground", None)
                if publish_method is None:
                    raise ValueError("当前粘贴适配器不支持自动发布。")
                result = self._call_paste_method(publish_method, reply)
                if getattr(result, "action", "") in {"sent_verified", "sent_unverified"}:
                    self._mark_event_replied(item.event.event_id, reply)
                operator_action = self._operator_action_for_publish_result(result)
                self.session.record_operator_action(item, reply, operator_action=operator_action, action="auto_publish")
                return self._paste_result_payload(result)

    def _paste_result_payload(self, result: Any) -> dict[str, str]:
        return {
            "status": "ok",
            "paste_action": result.action,
            "message": result.message,
            "foreground_window_title": result.foreground_window_title,
            "target_status": getattr(result, "target_status", "unknown"),
            "input_status": getattr(result, "input_status", "unknown"),
            "verification_status": getattr(result, "verification_status", "unverified"),
            "fallback_reason": getattr(result, "fallback_reason", ""),
        }

    def _call_paste_method(self, method: Any, reply: str) -> Any:
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(reply)
        if "target_group_name" in signature.parameters:
            return method(reply, target_group_name=self.wechat_config.group_name)
        return method(reply)

    def _operator_action_for_paste_result(self, result: Any) -> str:
        action = getattr(result, "action", "")
        fallback_reason = getattr(result, "fallback_reason", "")
        fallback_actions = {
            "target_chat_not_found",
            "target_chat_ambiguous",
            "input_not_found",
            "input_not_empty",
            "fill_failed",
        }
        if action in {"filled_verified", "filled_unverified"}:
            return action
        if fallback_reason in fallback_actions:
            return fallback_reason
        if action == "copied":
            return "copied_to_clipboard"
        return "fill_failed"

    def _operator_action_for_publish_result(self, result: Any) -> str:
        action = getattr(result, "action", "")
        if action in {"sent_verified", "sent_unverified"}:
            return "auto_sent_to_wechat"
        if action in {"filled_verified", "filled_unverified"}:
            return "auto_send_blocked_after_fill"
        return self._operator_action_for_paste_result(result)

    def confirm_sent(self, event_id: str, reply: str) -> dict[str, str]:
        item = self._find_item(event_id)
        self.session.confirm_operator_sent(item, reply)
        self._mark_event_replied(item.event.event_id, reply)
        return {"status": "ok", "message": "已记录运营确认发送"}

    def get_vision_status(self) -> dict[str, Any]:
        return serialize_vision_state(self.vision_observer.state)

    def start_vision(self) -> dict[str, Any]:
        vision = self.vision_observer.start()
        if self.wechat_listener is None:
            self.wechat_listener = WeFlowLiveListener(self.wechat_config)
        self.wechat_listener_running = True
        self.recent_logs.append("微信视觉观察器已启动")
        polled = self.poll_wechat_once()
        return {**polled, "vision": serialize_vision_state(vision)}

    def stop_vision(self) -> dict[str, Any]:
        vision = self.vision_observer.stop()
        self.wechat_listener_running = False
        self.recent_logs.append("微信视觉观察器已停止")
        return {
            "status": "ok",
            "message": "微信视觉观察器已停止",
            "items": self._serialize_items(),
            "vision": serialize_vision_state(vision),
        }

    def capture_vision_once(self) -> dict[str, Any]:
        capture = self.vision_window_backend.capture_wechat_window()
        if capture.status != "ok":
            running = self.vision_observer.state.running
            vision = VisionState(
                running=running,
                window_title=capture.window_title,
                last_message=self.vision_observer.state.last_message,
                last_error=capture.message,
            )
            self.vision_observer.state = vision
            self.recent_logs.append(capture.message)
            return {
                "status": capture.status,
                "message": capture.message,
                "items": self._serialize_items(),
                "vision": serialize_vision_state(vision),
            }

        result = self.vision_observer.capture_once(
            capture.screenshot,
            window_title=capture.window_title,
            group_name=self.group_config.group_name,
        )
        self._append_listener_events(result.events)
        self.recent_logs.append(result.message)
        return {
            "status": result.status,
            "message": result.message,
            "items": self._serialize_items(),
            "vision": serialize_vision_state(result.vision),
        }

    def _find_item(self, event_id: str) -> WorkbenchItem:
        for item in self.items:
            if item.event.event_id == event_id:
                return item
        raise ValueError("没有找到对应消息，请重新选择")

    def _sync_group_config_from_wechat(self) -> None:
        self._set_group_config(
            GroupConfig(
                group_name=self.wechat_config.group_name,
                group_id_hash=self.group_config.group_id_hash,
                enabled=self.wechat_config.enabled,
                mode="auto" if self.wechat_config.send_mode == SEND_MODE_AUTO_SEND else "semi_auto",
                keywords=[*self.wechat_config.keywords],
                agent_mentions=[*self.group_config.agent_mentions],
                auto_reply_intents=[*self.group_config.auto_reply_intents],
                daily_auto_reply_limit=self.group_config.daily_auto_reply_limit,
            )
        )

    def _set_group_config(self, group_config: GroupConfig) -> None:
        self.group_config = group_config
        self.session.update_group_config(group_config)

    def _refresh_wechat_listener_if_running(self) -> None:
        if self.wechat_listener_running:
            self.wechat_listener = WeFlowLiveListener(self.wechat_config)

    def _reprocess_items(self) -> None:
        self.items = [self.session.process_event(item.event) for item in self.items]

    def _poll_wechat_listener(self) -> None:
        with self._poll_lock:
            if self.wechat_listener is None:
                return
            result = self._call_wechat_listener(include_seen=False)
            if result.status == "ok":
                self._append_listener_events(result.events)
            else:
                self.recent_logs.append(result.message)

    def _call_wechat_listener(self, *, include_seen: bool) -> Any:
        try:
            return self.wechat_listener.poll_once(include_seen=include_seen)
        except TypeError as exc:
            if "include_seen" not in str(exc):
                raise
            return self.wechat_listener.poll_once()

    def _append_listener_events(self, events: list[ChatEvent]) -> None:
        existing_ids = {item.event.event_id for item in self.items}
        for event in events:
            if event.event_id in existing_ids:
                continue
            self.inbox_store.upsert(event)
            item = self.session.process_event(event)
            self.items.append(item)
            existing_ids.add(event.event_id)
            if item.reply_decision.mode != "auto_send" or not item.reply_decision.reply.strip():
                continue
            try:
                result = self.publish_reply(item.event.event_id, item.reply_decision.reply)
                self.recent_logs.append(f"自动回复：{event.sender_alias} · {result['message']}")
            except Exception as exc:  # noqa: BLE001 - 单条发送失败不能中断后续监听
                self.recent_logs.append(f"自动回复失败：{event.sender_alias} · {exc}")

    def _mark_event_replied(self, event_id: str, reply: str = "") -> None:
        self._replied_event_ids.add(event_id)
        try:
            self.inbox_store.remove(event_id)
        except OSError as exc:
            self.recent_logs.append(f"清理工作台收件箱失败：{exc}")
        mark_replied = getattr(self.wechat_listener, "mark_replied", None)
        if mark_replied is None:
            return
        try:
            mark_replied(event_id, reply)
        except Exception as exc:  # noqa: BLE001 - 发送结果仍需返回给界面
            self.recent_logs.append(f"保存已回复标记失败：{exc}")

    def _is_event_replied(self, event_id: str) -> bool:
        if event_id in self._replied_event_ids:
            return True
        is_replied = getattr(self.wechat_listener, "is_replied", None)
        if is_replied is None:
            return False
        try:
            return bool(is_replied(event_id))
        except Exception as exc:  # noqa: BLE001 - 状态不可读时保守阻止重复发送
            self.recent_logs.append(f"读取已回复标记失败：{exc}")
            return True

    def _serialize_item(self, item: WorkbenchItem) -> dict[str, Any]:
        replied = self._is_event_replied(item.event.event_id)
        return serialize_item(item, replied=replied)

    def _serialize_items(self) -> list[dict[str, Any]]:
        return [self._serialize_item(item) for item in self.items]

    def _default_trace_path(self, candidate_path: str | Path) -> Path:
        candidate = Path(candidate_path)
        if candidate == DEFAULT_CANDIDATE_PATH:
            return DEFAULT_TRACE_PATH
        return candidate.parent / "work_trace.jsonl"


def serialize_item(item: WorkbenchItem, *, replied: bool = False) -> dict[str, Any]:
    return {
        "event_id": item.event.event_id,
        "group_name": item.event.group_name,
        "sender": item.event.sender_alias,
        "message_time": item.event.message_time,
        "question": item.event.content,
        "source": item.event.source,
        "summary": format_item_summary(item, replied=replied),
        "status": status_label(item, replied=replied),
        "replied": replied,
        "mode": item.reply_decision.mode,
        "reply": item.reply_decision.reply,
        "trigger_reasons": item.trigger.reasons,
        "matched_keywords": item.trigger.matched_keywords,
        "recommendation": item.review_card.recommendation,
        "engine_action": item.review_card.action,
        "intent": item.review_card.intent,
        "answer_source": item.review_card.source,
        "confidence": item.review_card.confidence,
        "generation_mode": item.review_card.generation_mode,
        "generation_model": item.review_card.generation_model,
        "generation_error": item.review_card.generation_error,
        "reason": item.reply_decision.reason or item.review_card.reason,
    }


def serialize_vision_state(state: VisionState) -> dict[str, Any]:
    return {
        "running": state.running,
        "window_title": state.window_title,
        "last_message": state.last_message,
        "last_error": state.last_error,
    }


def create_handler(state: WorkbenchApiState):
    class WorkbenchRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._send_json({"error": "桌面版已替代网页工作台"}, status=404)
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
            if path == "/api/app/status":
                self._send_json(state.get_app_status())
                return
            if path == "/api/app/settings":
                self._send_json(state.get_app_settings())
                return
            if path == "/api/app/work-trace":
                self._send_json(state.list_work_trace())
                return
            if path == "/api/vision/status":
                self._send_json(state.get_vision_status())
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
                if path == "/api/import-weflow":
                    self._send_json(state.import_weflow_group(str(payload.get("group_name") or "")))
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
                if path == "/api/wechat/publish":
                    self._send_json(state.publish_reply(str(payload.get("event_id") or ""), str(payload.get("reply") or "")))
                    return
                if path == "/api/wechat/confirm-sent":
                    self._send_json(state.confirm_sent(str(payload.get("event_id") or ""), str(payload.get("reply") or "")))
                    return
                if path == "/api/vision/start":
                    self._send_json(state.start_vision())
                    return
                if path == "/api/vision/stop":
                    self._send_json(state.stop_vision())
                    return
                if path == "/api/vision/capture":
                    self._send_json(state.capture_vision_once())
                    return
                if path == "/api/app/start":
                    self._send_json(state.start_app())
                    return
                if path == "/api/app/stop":
                    self._send_json(state.stop_app())
                    return
                if path == "/api/app/settings":
                    self._send_json(state.update_app_settings(payload))
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


