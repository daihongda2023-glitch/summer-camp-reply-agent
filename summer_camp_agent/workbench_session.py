from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .chat_log_sanitizer import hash_identifier
from .engine import AnswerEngine
from .knowledge import KnowledgeBase
from .review import OperatorReview, ReviewCard
from .workbench_models import (
    ChatEvent,
    GroupConfig,
    ReplyCandidate,
    ReplyDecision,
    ReplyLogEntry,
    TriggerDecision,
)
from .workbench_modes import ReplyModeController
from .workbench_store import ReplyCandidateStore, ReplyLogStore
from .workbench_trigger import TriggerEngine


DEFAULT_CANDIDATE_PATH = Path(__file__).resolve().parents[1] / "data" / "reply_candidates.jsonl"
DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "reply_logs.jsonl"


@dataclass(frozen=True)
class WorkbenchItem:
    event: ChatEvent
    trigger: TriggerDecision
    review_card: ReviewCard
    reply_decision: ReplyDecision


class WorkbenchSession:
    def __init__(
        self,
        group_config: GroupConfig,
        candidate_path: str | Path = DEFAULT_CANDIDATE_PATH,
        log_path: str | Path = DEFAULT_LOG_PATH,
        review: OperatorReview | None = None,
    ):
        self.group_config = group_config
        self.trigger_engine = TriggerEngine(group_config)
        self.review = review or OperatorReview(AnswerEngine(KnowledgeBase.from_default()))
        self.reply_modes = ReplyModeController(group_config)
        self.candidate_store = ReplyCandidateStore(candidate_path)
        self.log_store = ReplyLogStore(log_path)

    def process_event(self, event: ChatEvent) -> WorkbenchItem:
        trigger = self.trigger_engine.decide(event)
        if trigger.should_process:
            card = self.review.create_card(event.content)
        else:
            card = ReviewCard(
                original_question=event.content,
                recommendation="ignore",
                available_actions=[],
                action="ignored",
                reply="",
                reason="not_triggered",
            )
        decision = self.reply_modes.decide(trigger, card)
        return WorkbenchItem(event=event, trigger=trigger, review_card=card, reply_decision=decision)

    def confirm_reply(self, item: WorkbenchItem, edited_reply: str) -> None:
        reply = edited_reply.strip()
        if not reply:
            return

        now = datetime.now(timezone.utc).isoformat()
        if reply != item.review_card.reply.strip():
            self._append_candidate(item, reply, now)

        operator_action = "edited_and_sent" if reply != item.review_card.reply.strip() else "sent"
        self.log_store.append(
            ReplyLogEntry(
                log_id=hash_identifier(f"{item.event.event_id}:{reply}:{now}"),
                group_name=item.event.group_name,
                trigger_message_hash=hash_identifier(item.event.event_id),
                trigger_reasons=item.trigger.reasons,
                mode=item.reply_decision.mode,
                action="send",
                reply=reply,
                source=item.review_card.source,
                confidence=item.review_card.confidence,
                operator_action=operator_action,
                created_at=now,
            )
        )

    def save_candidate(self, item: WorkbenchItem, edited_reply: str, candidate_type: str = "faq") -> bool:
        reply = edited_reply.strip()
        if not reply:
            return False
        self._append_candidate(item, reply, datetime.now(timezone.utc).isoformat(), candidate_type)
        return True

    def _append_candidate(
        self,
        item: WorkbenchItem,
        reply: str,
        created_at: str,
        candidate_type: str = "faq",
    ) -> None:
        self.candidate_store.append(
            ReplyCandidate(
                candidate_id=hash_identifier(f"{item.event.event_id}:{reply}"),
                group_name=item.event.group_name,
                original_question=item.event.content,
                agent_reply=item.review_card.reply,
                edited_reply=reply,
                source=item.review_card.source or "人工修改",
                confidence=item.review_card.confidence,
                candidate_type=candidate_type,
                status="pending",
                created_at=created_at,
            )
        )
