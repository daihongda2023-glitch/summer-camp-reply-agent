from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.verify_semantic_reply_scenarios import (
    QUESTIONS,
    ScenarioPasteAdapter,
    ScenarioRagAnswerGenerator,
    ScenarioSemanticAnalyzer,
)
from summer_camp_agent.wechat_live_listener import ListenerPollResult
from summer_camp_agent.workbench_api import WorkbenchApiState
from summer_camp_agent.workbench_models import ChatEvent


ORDINARY_MESSAGE = "今天天气不错"
EVENTS = [
    ("debug-xpuoj", QUESTIONS[0]),
    ("debug-support", QUESTIONS[1]),
    ("debug-location", QUESTIONS[2]),
    ("debug-ordinary", ORDINARY_MESSAGE),
]


class DebugScenarioListener:
    def __init__(self, events: list[ChatEvent]):
        self.events = events
        self.replied_event_ids: list[str] = []

    def poll_once(self, *, include_seen: bool = False) -> ListenerPollResult:
        events, self.events = self.events, []
        return ListenerPollResult(
            "ok",
            f"已拉取 {len(events)} 条调试审核消息",
            events,
        )

    def mark_replied(self, event_id: str, reply: str = "") -> None:
        self.replied_event_ids.append(event_id)

    def is_replied(self, event_id: str) -> bool:
        return event_id in self.replied_event_ids


def run_verification(root: Path) -> dict[str, object]:
    paths = {
        "candidate_path": root / "reply_candidates.jsonl",
        "log_path": root / "reply_logs.jsonl",
        "trace_path": root / "work_trace.jsonl",
        "inbox_path": root / "workbench_inbox.jsonl",
        "message_db_path": root / "workbench_messages.sqlite3",
        "wechat_config_path": root / "wechat_bridge_config.json",
        "desktop_settings_path": root / "desktop_settings.json",
    }
    analyzer = ScenarioSemanticAnalyzer()
    generator = ScenarioRagAnswerGenerator()
    state = WorkbenchApiState(
        **paths,
        semantic_analyzer=analyzer,
        rag_answer_generator=generator,
    )
    state.configure_wechat(
        {
            "base_url": "http://127.0.0.1:5031",
            "token_env": "WEFLOW_API_TOKEN",
            "group_name": "测试工具",
            "session_id": "",
            "keywords": ["XPUOJ", "夏令营", "线下"],
            "poll_interval_seconds": 5,
            "enabled": True,
            "show_debug_config": False,
            "send_mode": "auto_send",
            "debug_review_mode": True,
        }
    )
    listener = DebugScenarioListener(_events())
    paste_adapter = ScenarioPasteAdapter()
    state.wechat_listener = listener
    state.paste_adapter = paste_adapter

    payload = state.poll_wechat_once()
    pending_items = payload["items"]
    items_by_question = {
        str(item["question"]): item
        for item in pending_items
    }
    results = {
        question: _diagnostic_result(item)
        for question, item in items_by_question.items()
    }

    xpuoj = items_by_question[QUESTIONS[0]]
    support = items_by_question[QUESTIONS[1]]
    location = items_by_question[QUESTIONS[2]]
    ordinary = items_by_question[ORDINARY_MESSAGE]
    state.complete_review(
        str(xpuoj["message_id"]),
        "现有资料不足以解释具体计分差异，建议保留评测记录后人工核查。",
    )
    state.escalate_message(
        str(support["message_id"]),
        "转交课程助教确认具体联系人。",
    )
    state.confirm_sent(
        str(location["message_id"]),
        str(location["reply"]),
    )
    state.complete_review(
        str(ordinary["message_id"]),
        "普通聊天，无需回复。",
    )

    history = state.list_items(scope="all")["items"]
    restarted = WorkbenchApiState(
        **paths,
        semantic_analyzer=analyzer,
        rag_answer_generator=generator,
    )
    return {
        "status": payload["status"],
        "pending_before_actions": len(pending_items),
        "results": results,
        "auto_sent": paste_adapter.sent,
        "history_statuses": {
            str(item["message_id"]): str(item["review_status"])
            for item in history
        },
        "pending_after_actions": len(state.list_items()["items"]),
        "pending_after_restart": len(restarted.list_items()["items"]),
    }


def _diagnostic_result(item: dict[str, object]) -> dict[str, object]:
    return {
        "message_id": item["message_id"],
        "question": item["question"],
        "reply": item["reply"],
        "review_status_before": item["review_status"],
        "match_status": item["match_status"],
        "unmatched_reasons": item["unmatched_reasons"],
        "unmatched_reason_labels": item["unmatched_reason_labels"],
        "confidence": item["confidence"],
        "semantic_confidence": item["semantic_confidence"],
        "faq_confidence": item["faq_confidence"],
        "rag_confidence": item["rag_confidence"],
        "semantic_intent": item["semantic_intent"],
        "generation_mode": item["generation_mode"],
        "reason": item["reason"],
    }


def _events() -> list[ChatEvent]:
    return [
        ChatEvent(
            event_id=event_id,
            group_id_hash="sha256:debug-review-group",
            group_name="测试工具",
            sender_alias="成员001",
            sender_role="student",
            message_time=f"2026-07-25 22:0{index}:00",
            content=question,
            raw_type="text",
            source="debug_workflow_validation",
        )
        for index, (event_id, question) in enumerate(EVENTS, start=1)
    ]


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        result = run_verification(Path(directory))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
