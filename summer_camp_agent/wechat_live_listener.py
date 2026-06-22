from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from typing import Any, Callable

from .chat_log_sanitizer import AliasRegistry, build_sanitized_message
from .wechat_bridge_config import ListenerStateStore, WeChatBridgeConfig
from .weflow_import import (
    WeFlowAuthError,
    WeFlowImportClient,
    WeFlowImportError,
    WeFlowSession,
    WeFlowSessionNotFoundError,
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
        clock: Callable[[], datetime] | None = None,
    ):
        self.config = config
        self.state_store = state_store or ListenerStateStore()
        self.token = token
        self.client = client
        self.clock = clock or datetime.now
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
            since = int((self.clock() - timedelta(hours=1)).timestamp())
            payload = client.pull_messages(session.id, since=since, end=None, limit=100, offset=0)
            events: list[ChatEvent] = []
            for raw in payload.get("messages", []):
                if not isinstance(raw, dict):
                    continue
                if int(raw.get("timestamp") or 0) < since:
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
        if not sessions:
            raise WeFlowSessionNotFoundError(f"没有找到匹配群聊：{self.config.group_name}")
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
