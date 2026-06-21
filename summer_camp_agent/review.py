from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .engine import AnswerEngine


AVAILABLE_ACTIONS = ["send", "edit", "escalate", "mark_pending"]


@dataclass(frozen=True)
class ReviewCard:
    original_question: str
    recommendation: str
    available_actions: list[str]
    action: str
    reply: str
    intent: str = ""
    source: str = ""
    reason: str = ""
    confidence: float = 0.0


class OperatorReview:
    def __init__(self, engine: AnswerEngine):
        self.engine = engine

    def create_card(self, question: str) -> ReviewCard:
        result = self.engine.answer(question)
        return ReviewCard(
            original_question=question,
            recommendation=self._recommendation_for(result.action),
            available_actions=[*AVAILABLE_ACTIONS],
            action=result.action,
            reply=result.reply,
            intent=result.intent,
            source=result.source,
            reason=result.reason,
            confidence=result.confidence,
        )

    @staticmethod
    def _recommendation_for(action: str) -> str:
        if action == "auto_reply":
            return "send"
        if action == "human_fallback":
            return "escalate"
        return "mark_pending"


def save_pending_question(card: ReviewCard, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "original_question": card.original_question,
        "reply": card.reply,
        "reason": card.reason or "unknown",
        "status": "待确认",
        "recommended_owner": "运营",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
