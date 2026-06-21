from __future__ import annotations

from .workbench_models import ChatEvent
from .workbench_session import WorkbenchItem


def build_demo_events() -> list[ChatEvent]:
    base = {
        "group_id_hash": "sha256:demo-group",
        "group_name": "夏令营咨询群",
        "sender_role": "student",
        "raw_type": "text",
        "source": "demo",
    }
    rows = [
        ("demo-1", "成员001", "2026-06-21 10:00:00", "报名入口在哪里？"),
        ("demo-2", "成员002", "2026-06-21 10:03:00", "住宿怎么安排？"),
        ("demo-3", "成员003", "2026-06-21 10:06:00", "夏令营我被录取了吗？"),
        ("demo-4", "成员004", "2026-06-21 10:09:00", "夏令营集合要带雨伞吗？"),
        ("demo-5", "成员005", "2026-06-21 10:12:00", "收到，谢谢老师"),
    ]
    return [
        ChatEvent(
            event_id=event_id,
            sender_alias=sender,
            message_time=message_time,
            content=content,
            **base,
        )
        for event_id, sender, message_time, content in rows
    ]


def format_item_summary(item: WorkbenchItem) -> str:
    reasons = "+".join(item.trigger.reasons) if item.trigger.reasons else "无触发"
    message_time = item.event.message_time[-8:] if item.event.message_time else "--:--:--"
    content = truncate_text(item.event.content, 38)
    return f"[{status_label(item)}] {message_time} {item.event.sender_alias}：{content}（{reasons}）"


def status_label(item: WorkbenchItem) -> str:
    return {
        "draft": "待审核",
        "auto_send": "可自动",
        "escalate": "转人工",
        "mark_pending": "待补充",
        "ignored": "未触发",
    }.get(item.reply_decision.mode, item.reply_decision.mode)


def truncate_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"
