from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Callable

from .chat_log_sanitizer import AliasRegistry, build_sanitized_message, hash_identifier
from .wechat_bridge_config import ListenerStateStore, WeChatBridgeConfig
from .weflow_import import (
    WeFlowAuthError,
    WeFlowImportClient,
    WeFlowImportError,
    WeFlowSession,
    WeFlowSessionNotFoundError,
    WeFlowSessionSelectionRequired,
    resolve_weflow_token,
)
from .workbench_models import ChatEvent, GroupConfig
from .workbench_trigger import TriggerEngine


@dataclass(frozen=True)
class ListenerPollResult:
    status: str
    message: str
    events: list[ChatEvent]


MESSAGE_ID_FIELDS = ("platformMessageId", "id", "messageId", "msgId", "clientMsgId", "localId")
SENDER_ID_FIELDS = ("sender", "senderUsername", "fromUser", "fromUsername", "talker", "from")
SENDER_NAME_FIELDS = (
    "senderName",
    "senderNickname",
    "senderDisplayName",
    "senderRemark",
    "displayName",
    "nickname",
    "name",
    "remark",
)
MEMBER_ID_FIELDS = ("platformId", "id", "username", "userName", "wxid", "sender", "senderUsername")
MEMBER_NAME_FIELDS = ("name", "displayName", "nickname", "remark", "alias")
QUOTE_FIELDS = (
    "quoteMessageId",
    "quotedMessageId",
    "quoteId",
    "quotedId",
    "referMessageId",
    "referMsgId",
    "replyToMessageId",
    "replyToMsgId",
    "replyTo",
    "quote",
    "quoted",
    "reference",
    "refer",
)
MENTION_FIELDS = ("mentions", "mentioned", "atUsers", "atUserList", "at_user_list", "atList", "at")


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
        self._state_lock = RLock()

    def poll_once(self, *, include_seen: bool = False) -> ListenerPollResult:
        with self._state_lock:
            return self._poll_once(include_seen=include_seen)

    def _poll_once(self, *, include_seen: bool = False) -> ListenerPollResult:
        try:
            token_value = resolve_weflow_token(self.config.token_env, explicit_token=self.token)
        except WeFlowAuthError as exc:
            return ListenerPollResult("error", str(exc), [])
        try:
            client = self.client or WeFlowImportClient(self.config.base_url, token_value)
            session = self._resolve_session(client)
            state = self.state_store.load().with_session_id(session.id)
            since = int((self.clock() - timedelta(hours=1)).timestamp())
            payload = client.pull_messages(session.id, since=since, end=None, limit=100, offset=0)
            raw_messages = [raw for raw in payload.get("messages", []) if isinstance(raw, dict)]
            member_aliases = _member_aliases(payload)
            self_sender_ids = _self_sender_ids(payload)
            replied_message_ids = _find_replied_message_ids(raw_messages, member_aliases)
            sent_reply_hashes = set(state.sent_reply_hashes)
            events: list[ChatEvent] = []
            for raw in raw_messages:
                if int(raw.get("timestamp") or 0) < since:
                    continue
                if _raw_message_id(raw) in replied_message_ids:
                    continue
                if _is_self_message(raw, self_sender_ids):
                    continue
                if _is_known_self_sent_reply(raw, sent_reply_hashes):
                    continue
                event = self._event_from_raw(raw, session)
                if event is None:
                    continue
                # 调试模式的人工拉取需要把旧版本误标为“已回复”的已看消息
                # 交给 SQLite 主存储重新核对；已有记录会在工作台按 event_id 去重。
                if (
                    event.event_id in state.replied_event_ids
                    and not (self.config.debug_review_mode and include_seen)
                ):
                    continue
                if event.event_id in state.seen_event_ids and not include_seen:
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

    def mark_replied(self, event_id: str, reply: str = "") -> None:
        value = event_id.strip()
        if not value:
            return
        with self._state_lock:
            state = self.state_store.load().with_replied_event(value)
            self.state_store.save(state.with_sent_reply(reply))

    def is_replied(self, event_id: str) -> bool:
        value = event_id.strip()
        if not value:
            return False
        with self._state_lock:
            return value in self.state_store.load().replied_event_ids

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
            # 实时监听必须先保留消息，再由统一触发引擎判断；否则“@智能体”
            # 和“问号 + 夏令营词”会被关键字预过滤提前丢弃。
            keywords=[],
            platform_message_id=str(raw.get("platformMessageId") or raw.get("id") or timestamp),
            raw_type=raw.get("type", "text"),
            alias_registry=self.alias_registry,
            include_media=False,
        )
        if message is None:
            return None
        event = ChatEvent(
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
        if self.config.debug_review_mode:
            return event
        trigger = TriggerEngine(
            GroupConfig(group_name=session.name, keywords=[*self.config.keywords])
        ).decide(event)
        return event if trigger.should_process else None


def _is_known_self_sent_reply(raw: dict[str, Any], sent_reply_hashes: set[str]) -> bool:
    if not sent_reply_hashes or not _is_self_message(raw):
        return False
    content = str(raw.get("content") or "").strip()
    return bool(content) and hash_identifier(content) in sent_reply_hashes


def _is_self_message(raw: dict[str, Any], self_sender_ids: set[str] | None = None) -> bool:
    for field in ("isSelf", "isSend", "fromMe", "sentBySelf"):
        value = raw.get(field)
        if value is True or str(value).strip().lower() in {"1", "true", "yes"}:
            return True
    direction = str(raw.get("direction") or "").strip().lower()
    if direction in {"outbound", "outgoing", "sent"}:
        return True
    account_name = str(raw.get("accountName") or "").strip().lower()
    if account_name in {"我", "me", "self"}:
        return True
    known_ids = self_sender_ids or set()
    return any(str(raw.get(field) or "").strip() in known_ids for field in SENDER_ID_FIELDS)


def _self_sender_ids(payload: dict[str, Any]) -> set[str]:
    raw_members = payload.get("members")
    if isinstance(raw_members, dict):
        iterable = [
            ({**value, "id": key} if isinstance(value, dict) else {"id": key, "name": value})
            for key, value in raw_members.items()
        ]
    elif isinstance(raw_members, list):
        iterable = [member for member in raw_members if isinstance(member, dict)]
    else:
        iterable = []

    self_ids: set[str] = set()
    for member in iterable:
        names = {
            str(member.get(field) or "").strip().lower()
            for field in ("accountName", *MEMBER_NAME_FIELDS)
        }
        if not names.intersection({"我", "me", "self"}):
            continue
        for field in MEMBER_ID_FIELDS:
            value = str(member.get(field) or "").strip()
            if value:
                self_ids.add(value)
                break
    return self_ids


def _find_replied_message_ids(raw_messages: list[dict[str, Any]], member_aliases: dict[str, set[str]]) -> set[str]:
    replied: set[str] = set()
    for index, raw in enumerate(raw_messages):
        message_id = _raw_message_id(raw)
        if not message_id:
            continue
        sender_refs = _sender_reference_terms(raw, member_aliases)
        timestamp = int(raw.get("timestamp") or 0)
        for later in raw_messages[index + 1 :]:
            later_timestamp = int(later.get("timestamp") or 0)
            if timestamp and later_timestamp and later_timestamp <= timestamp:
                continue
            if _quotes_message(later, message_id) or _mentions_sender(later, sender_refs):
                replied.add(message_id)
                break
    return replied


def _raw_message_id(raw: dict[str, Any]) -> str:
    for field in MESSAGE_ID_FIELDS:
        value = str(raw.get(field) or "").strip()
        if value:
            return value
    return ""


def _sender_reference_terms(raw: dict[str, Any], member_aliases: dict[str, set[str]]) -> set[str]:
    refs: set[str] = set()
    sender_id = ""
    for field in SENDER_ID_FIELDS:
        value = str(raw.get(field) or "").strip()
        if value:
            sender_id = value
            refs.add(value)
            break
    for field in SENDER_NAME_FIELDS:
        value = str(raw.get(field) or "").strip()
        if value:
            refs.add(value)
    if sender_id:
        refs.update(member_aliases.get(sender_id, set()))
    return {ref for ref in refs if ref}


def _member_aliases(payload: dict[str, Any]) -> dict[str, set[str]]:
    raw_members = payload.get("members")
    aliases: dict[str, set[str]] = {}
    if isinstance(raw_members, dict):
        iterable = []
        for key, value in raw_members.items():
            if isinstance(value, dict):
                iterable.append({**value, "id": key})
            else:
                iterable.append({"id": key, "name": value})
    elif isinstance(raw_members, list):
        iterable = [member for member in raw_members if isinstance(member, dict)]
    else:
        iterable = []

    for member in iterable:
        member_id = ""
        for field in MEMBER_ID_FIELDS:
            value = str(member.get(field) or "").strip()
            if value:
                member_id = value
                break
        if not member_id:
            continue
        names = aliases.setdefault(member_id, set())
        for field in MEMBER_NAME_FIELDS:
            value = str(member.get(field) or "").strip()
            if value:
                names.add(value)
    return aliases


def _quotes_message(raw: dict[str, Any], message_id: str) -> bool:
    if not message_id:
        return False
    return any(field in raw and message_id in _flatten_reference_values(raw[field]) for field in QUOTE_FIELDS)


def _mentions_sender(raw: dict[str, Any], sender_refs: set[str]) -> bool:
    if not sender_refs:
        return False
    content = str(raw.get("content") or "")
    if any(f"@{ref}" in content for ref in sender_refs):
        return True
    for field in MENTION_FIELDS:
        if field not in raw:
            continue
        values = _flatten_reference_values(raw[field])
        if any(ref in values for ref in sender_refs):
            return True
    msg_source = str(raw.get("msgSource") or raw.get("messageSource") or "")
    return any(ref and ref in msg_source for ref in sender_refs)


def _flatten_reference_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (str, int)):
        text = str(value).strip()
        return {text} if text else set()
    if isinstance(value, dict):
        values: set[str] = set()
        for nested in value.values():
            values.update(_flatten_reference_values(nested))
        return values
    if isinstance(value, list):
        values: set[str] = set()
        for item in value:
            values.update(_flatten_reference_values(item))
        return values
    return set()
