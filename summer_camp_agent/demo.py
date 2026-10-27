from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .activity import ActivityProfile, load_activity
from .engine import AnswerEngine
from .knowledge import KnowledgeBase


DEMO_CASES = [
    ("summer-camp", date(2026, 7, 10), "报名入口在哪里？", "auto_reply", "registration.link"),
    ("summer-camp", date(2026, 7, 10), "线下夏令营在哪里举办？", "auto_reply", "offline.location"),
    ("online-workshop", None, "直播链接在哪里？", "auto_reply", "session.link"),
    ("online-workshop", None, "有线下会场吗？", "auto_reply", "format.online_only"),
    ("offline-meetup", None, "活动地点在哪里？", "auto_reply", "venue.address"),
    ("offline-meetup", None, "有直播链接吗？", "auto_reply", "format.offline_only"),
    ("hybrid-summit", None, "线上入口在哪里？", "auto_reply", "session.link"),
    ("hybrid-summit", None, "线下地点在哪里？", "auto_reply", "venue.address"),
    ("hybrid-summit", None, "可以只参加线上吗？", "auto_reply", "attendance.choice"),
    ("hybrid-summit", None, "我被录取了吗？", "human_fallback", ""),
]


@dataclass(frozen=True)
class DemoRow:
    activity_id: str
    formats: tuple[str, ...]
    question: str
    expected_action: str
    action: str
    intent: str
    ok: bool
    reply: str


def run_demo() -> list[DemoRow]:
    rows: list[DemoRow] = []
    for activity_id, on_date, question, expected_action, expected_intent in DEMO_CASES:
        profile = load_activity(activity_id)
        result = _engine_for(profile, on_date).answer(question)
        ok = result.action == expected_action and (not expected_intent or result.intent == expected_intent)
        rows.append(
            DemoRow(
                activity_id=profile.id,
                formats=profile.formats,
                question=question,
                expected_action=expected_action,
                action=result.action,
                intent=result.intent,
                ok=ok,
                reply=result.reply,
            )
        )
    return rows


def _engine_for(profile: ActivityProfile, on_date: date | None) -> AnswerEngine:
    if profile.id == "summer-camp":
        knowledge = KnowledgeBase.from_default()
    else:
        knowledge = KnowledgeBase.from_json(profile.knowledge_path)
    return AnswerEngine(
        knowledge,
        today=on_date,
        organizer=profile.organizer,
        notice_channel=profile.notice_channel,
        assignment_contact=profile.assignment_contact,
    )
