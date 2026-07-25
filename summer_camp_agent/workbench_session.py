from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .chat_log_sanitizer import hash_identifier
from .engine import AnswerEngine
from .knowledge import KnowledgeBase
from .rag_runtime import load_default_rag_retriever
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
from .work_trace import WorkTraceRecorder, WorkTraceStep


DEFAULT_CANDIDATE_PATH = Path(__file__).resolve().parents[1] / "data" / "reply_candidates.jsonl"
DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "reply_logs.jsonl"
DEFAULT_TRACE_PATH = Path(__file__).resolve().parents[1] / "data" / "work_trace.jsonl"


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
        trace_path: str | Path | None = None,
        review: OperatorReview | None = None,
        rag_answer_generator=None,
        semantic_analyzer=None,
    ):
        self.group_config = group_config
        self.trigger_engine = TriggerEngine(group_config)
        self.review = review or OperatorReview(
            AnswerEngine(
                KnowledgeBase.from_default(),
                rag_retriever=load_default_rag_retriever(),
                rag_answer_generator=rag_answer_generator,
                semantic_analyzer=semantic_analyzer,
            )
        )
        self.reply_modes = ReplyModeController(group_config)
        self.candidate_store = ReplyCandidateStore(candidate_path)
        self.log_store = ReplyLogStore(log_path)
        self.trace_recorder = WorkTraceRecorder(trace_path) if trace_path is not None else None

    def update_group_config(self, group_config: GroupConfig) -> None:
        self.group_config = group_config
        self.trigger_engine = TriggerEngine(group_config)
        self.reply_modes = ReplyModeController(group_config)

    def process_event(
        self,
        event: ChatEvent,
        *,
        debug_review_mode: bool = False,
    ) -> WorkbenchItem:
        trigger = self.trigger_engine.decide(event)
        self._trace(
            event,
            phase="observe",
            summary="收到群消息并完成触发判断",
            action="trigger_decision",
            outcome="ok" if trigger.should_process else "skip",
            details={
                "trigger_reasons": trigger.reasons,
                "matched_keywords": trigger.matched_keywords,
                "raw_type": event.raw_type,
                "source": event.source,
            },
        )
        if trigger.should_process or debug_review_mode:
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
        if debug_review_mode:
            decision = ReplyDecision(
                mode="draft",
                reply=card.reply,
                source=card.source,
                confidence=card.confidence,
                reason=card.reason or ("debug_unmatched" if not trigger.should_process else "debug_review"),
                requires_review=True,
            )
        self._trace(
            event,
            phase="think",
            summary="生成回复审核卡和模式决策",
            action=decision.mode,
            outcome=card.recommendation,
            reasoning=card.reason,
            details={
                "card_action": card.action,
                "intent": card.intent,
                "source": card.source,
                "confidence": card.confidence,
                "requires_review": decision.requires_review,
                "generation_mode": card.generation_mode,
                "generation_model": card.generation_model,
                "generation_error": card.generation_error,
                "semantic_status": card.semantic_status,
                "semantic_intent": card.semantic_intent,
                "semantic_question": card.semantic_question,
                "semantic_confidence": card.semantic_confidence,
                "semantic_model": card.semantic_model,
                "semantic_error": card.semantic_error,
                "faq_confidence": card.faq_confidence,
                "rag_confidence": card.rag_confidence,
                "rag_query": card.rag_query,
                "debug_review_mode": debug_review_mode,
            },
        )
        return WorkbenchItem(event=event, trigger=trigger, review_card=card, reply_decision=decision)

    def confirm_reply(self, item: WorkbenchItem, edited_reply: str) -> None:
        reply = edited_reply.strip()
        if not reply:
            return

        now = datetime.now(timezone.utc).isoformat()
        if reply != item.review_card.reply.strip():
            self._append_candidate(item, reply, now)

        operator_action = "edited_and_sent" if reply != item.review_card.reply.strip() else "sent"
        self._trace(
            item.event,
            phase="act",
            summary="确认发送回复",
            action="send",
            outcome="ok",
            details={
                "operator_action": operator_action,
                "mode": item.reply_decision.mode,
                "edited": reply != item.review_card.reply.strip(),
            },
        )
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
                generation_mode=item.review_card.generation_mode,
                generation_model=item.review_card.generation_model,
                generation_error=item.review_card.generation_error,
                semantic_status=item.review_card.semantic_status,
                semantic_intent=item.review_card.semantic_intent,
                semantic_question=item.review_card.semantic_question,
                semantic_confidence=item.review_card.semantic_confidence,
                semantic_model=item.review_card.semantic_model,
                semantic_error=item.review_card.semantic_error,
                faq_confidence=item.review_card.faq_confidence,
                rag_confidence=item.review_card.rag_confidence,
                rag_query=item.review_card.rag_query,
            )
        )

    def save_candidate(self, item: WorkbenchItem, edited_reply: str, candidate_type: str = "faq") -> bool:
        reply = edited_reply.strip()
        if not reply:
            return False
        self._trace(
            item.event,
            phase="act",
            summary="保存候选回复",
            action="save_candidate",
            outcome="ok",
            details={"candidate_type": candidate_type},
        )
        self._append_candidate(item, reply, datetime.now(timezone.utc).isoformat(), candidate_type)
        return True

    def confirm_operator_sent(self, item: WorkbenchItem, edited_reply: str) -> None:
        reply = edited_reply.strip()
        if not reply:
            return
        operator_action = "edited_and_confirmed_sent" if reply != item.review_card.reply.strip() else "operator_confirmed_sent"
        if operator_action == "edited_and_confirmed_sent":
            self._append_candidate(item, reply, datetime.now(timezone.utc).isoformat())
        self.record_operator_action(item, reply, operator_action=operator_action, action="confirm_sent")

    def record_operator_action(
        self,
        item: WorkbenchItem,
        reply: str,
        *,
        operator_action: str,
        action: str,
    ) -> None:
        text = reply.strip()
        if not text:
            return
        now = datetime.now(timezone.utc).isoformat()
        self._trace(
            item.event,
            phase="act",
            summary="记录人工操作",
            actor="human",
            action=action,
            outcome="ok",
            details={
                "operator_action": operator_action,
                "mode": item.reply_decision.mode,
            },
        )
        self.log_store.append(
            ReplyLogEntry(
                log_id=hash_identifier(f"{item.event.event_id}:{text}:{operator_action}:{now}"),
                group_name=item.event.group_name,
                trigger_message_hash=hash_identifier(item.event.event_id),
                trigger_reasons=item.trigger.reasons,
                mode=item.reply_decision.mode,
                action=action,
                reply=text,
                source=item.review_card.source,
                confidence=item.review_card.confidence,
                operator_action=operator_action,
                created_at=now,
                generation_mode=item.review_card.generation_mode,
                generation_model=item.review_card.generation_model,
                generation_error=item.review_card.generation_error,
                semantic_status=item.review_card.semantic_status,
                semantic_intent=item.review_card.semantic_intent,
                semantic_question=item.review_card.semantic_question,
                semantic_confidence=item.review_card.semantic_confidence,
                semantic_model=item.review_card.semantic_model,
                semantic_error=item.review_card.semantic_error,
                faq_confidence=item.review_card.faq_confidence,
                rag_confidence=item.review_card.rag_confidence,
                rag_query=item.review_card.rag_query,
            )
        )

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

    def _trace(
        self,
        event: ChatEvent,
        *,
        phase: str,
        summary: str,
        action: str = "",
        outcome: str = "",
        reasoning: str = "",
        actor: str = "agent",
        details: dict[str, object] | None = None,
    ) -> None:
        if self.trace_recorder is None:
            return
        self.trace_recorder.record(
            WorkTraceStep(
                event_id=event.event_id,
                group_name=event.group_name,
                phase=phase,
                summary=summary,
                actor=actor,
                action=action,
                outcome=outcome,
                reasoning=reasoning,
                details=details or {},
            )
        )
