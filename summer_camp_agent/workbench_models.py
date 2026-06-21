from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChatEvent:
    event_id: str
    group_id_hash: str
    group_name: str
    sender_alias: str
    sender_role: str
    message_time: str
    content: str
    raw_type: str
    source: str


@dataclass(frozen=True)
class GroupConfig:
    group_name: str
    group_id_hash: str = ""
    enabled: bool = True
    mode: str = "semi_auto"
    keywords: list[str] = field(
        default_factory=lambda: ["报名", "住宿", "交通", "作业", "面试", "通知", "报到", "GPU", "算子"]
    )
    agent_mentions: list[str] = field(default_factory=lambda: ["@Agent", "@夏令营助手"])
    auto_reply_intents: list[str] = field(default_factory=list)
    daily_auto_reply_limit: int = 50


@dataclass(frozen=True)
class TriggerDecision:
    should_process: bool
    reasons: list[str]
    matched_keywords: list[str]
