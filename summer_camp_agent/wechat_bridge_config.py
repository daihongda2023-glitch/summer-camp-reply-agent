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
DEFAULT_GROUP_NAME = "沐曦开源英才夏令营咨询群"
SEND_MODE_MANUAL_CONFIRM = "manual_confirm"
SEND_MODE_AUTO_SEND = "auto_send"
SEND_MODES = {SEND_MODE_MANUAL_CONFIRM, SEND_MODE_AUTO_SEND}


class WeChatBridgeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class WeChatBridgeConfig:
    base_url: str = "http://127.0.0.1:5031"
    token_env: str = "WEFLOW_API_TOKEN"
    group_name: str = DEFAULT_GROUP_NAME
    session_id: str = ""
    keywords: list[str] = field(default_factory=lambda: ["报名", "报到", "住宿", "交通", "作业", "面试", "GPU", "算子"])
    poll_interval_seconds: int = 5
    enabled: bool = True
    show_debug_config: bool = False
    send_mode: str = SEND_MODE_MANUAL_CONFIRM
    debug_review_mode: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WeChatBridgeConfig":
        config = cls(
            base_url=str(raw.get("base_url") or "http://127.0.0.1:5031"),
            token_env=str(raw.get("token_env") or "WEFLOW_API_TOKEN"),
            group_name=str(raw.get("group_name") or DEFAULT_GROUP_NAME),
            session_id=str(raw.get("session_id") or ""),
            keywords=[str(item).strip() for item in raw.get("keywords", []) if str(item).strip()],
            poll_interval_seconds=int(raw.get("poll_interval_seconds") or 5),
            enabled=bool(raw.get("enabled", True)),
            show_debug_config=bool(raw.get("show_debug_config", False)),
            send_mode=str(raw.get("send_mode") or SEND_MODE_MANUAL_CONFIRM),
            debug_review_mode=bool(raw.get("debug_review_mode", True)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise WeChatBridgeConfigError("WeFlow base_url 只允许连接本机 127.0.0.1 或 localhost。")
        if self.poll_interval_seconds < 2 or self.poll_interval_seconds > 60:
            raise WeChatBridgeConfigError("poll_interval_seconds 必须在 2 到 60 秒之间。")
        if self.send_mode not in SEND_MODES:
            raise WeChatBridgeConfigError("send_mode 必须是 manual_confirm 或 auto_send。")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class ListenerState:
    session_id_hash: str = ""
    last_poll_at: str = ""
    last_message_time: str = ""
    seen_event_ids: list[str] = field(default_factory=list)
    replied_event_ids: list[str] = field(default_factory=list)
    sent_reply_hashes: list[str] = field(default_factory=list)
    consecutive_errors: int = 0

    @classmethod
    def empty(cls) -> "ListenerState":
        return cls()

    @classmethod
    def from_dict(cls, raw: dict[str, Any], max_seen_ids: int = 2000) -> "ListenerState":
        seen_event_ids = [str(item) for item in raw.get("seen_event_ids", [])][-max_seen_ids:]
        raw_replied_event_ids = raw.get("replied_event_ids")
        replied_event_ids = (
            [*seen_event_ids]
            if raw_replied_event_ids is None
            else [str(item) for item in raw_replied_event_ids][-max_seen_ids:]
        )
        sent_reply_hashes = [str(item) for item in raw.get("sent_reply_hashes", [])][-max_seen_ids:]
        return cls(
            session_id_hash=str(raw.get("session_id_hash") or ""),
            last_poll_at=str(raw.get("last_poll_at") or ""),
            last_message_time=str(raw.get("last_message_time") or ""),
            seen_event_ids=seen_event_ids,
            replied_event_ids=replied_event_ids,
            sent_reply_hashes=sent_reply_hashes,
            consecutive_errors=int(raw.get("consecutive_errors") or 0),
        )

    def with_session_id(self, session_id: str) -> "ListenerState":
        return ListenerState(
            session_id_hash=hash_identifier(session_id),
            last_poll_at=self.last_poll_at,
            last_message_time=self.last_message_time,
            seen_event_ids=[*self.seen_event_ids],
            replied_event_ids=[*self.replied_event_ids],
            sent_reply_hashes=[*self.sent_reply_hashes],
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
            replied_event_ids=[*self.replied_event_ids][-max_seen_ids:],
            sent_reply_hashes=[*self.sent_reply_hashes][-max_seen_ids:],
            consecutive_errors=0,
        )

    def with_replied_event(self, event_id: str, max_seen_ids: int = 2000) -> "ListenerState":
        seen = [item for item in self.seen_event_ids if item != event_id]
        seen.append(event_id)
        replied = [item for item in self.replied_event_ids if item != event_id]
        replied.append(event_id)
        return ListenerState(
            session_id_hash=self.session_id_hash,
            last_poll_at=datetime.now(timezone.utc).isoformat(),
            last_message_time=self.last_message_time,
            seen_event_ids=seen[-max_seen_ids:],
            replied_event_ids=replied[-max_seen_ids:],
            sent_reply_hashes=[*self.sent_reply_hashes][-max_seen_ids:],
            consecutive_errors=0,
        )

    def with_sent_reply(self, reply: str, max_seen_ids: int = 2000) -> "ListenerState":
        value = reply.strip()
        if not value:
            return self
        reply_hash = hash_identifier(value)
        sent = [item for item in self.sent_reply_hashes if item != reply_hash]
        sent.append(reply_hash)
        return ListenerState(
            session_id_hash=self.session_id_hash,
            last_poll_at=self.last_poll_at,
            last_message_time=self.last_message_time,
            seen_event_ids=[*self.seen_event_ids][-max_seen_ids:],
            replied_event_ids=[*self.replied_event_ids][-max_seen_ids:],
            sent_reply_hashes=sent[-max_seen_ids:],
            consecutive_errors=self.consecutive_errors,
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
