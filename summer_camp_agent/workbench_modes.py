from __future__ import annotations

from .review import ReviewCard
from .workbench_models import GroupConfig, ReplyDecision, TriggerDecision


class ReplyModeController:
    def __init__(self, config: GroupConfig):
        self.config = config

    def decide(self, trigger: TriggerDecision, card: ReviewCard) -> ReplyDecision:
        if not trigger.should_process:
            return ReplyDecision(mode="ignored", reply="", reason="not_triggered", requires_review=False)
        if card.action == "human_fallback":
            return ReplyDecision(
                mode="escalate",
                reply=card.reply,
                source=card.source,
                confidence=card.confidence,
                reason=card.reason,
                requires_review=True,
            )
        if card.action != "auto_reply":
            return ReplyDecision(
                mode="mark_pending",
                reply=card.reply,
                source=card.source,
                confidence=card.confidence,
                reason=card.reason or "low_confidence",
                requires_review=True,
            )
        if self._can_auto_send(card):
            return ReplyDecision(
                mode="auto_send",
                reply=card.reply,
                source=card.source,
                confidence=card.confidence,
                requires_review=False,
            )
        return ReplyDecision(
            mode="draft",
            reply=card.reply,
            source=card.source,
            confidence=card.confidence,
            reason=card.reason,
            requires_review=True,
        )

    def _can_auto_send(self, card: ReviewCard) -> bool:
        # AnswerEngine 只会把命中的 FAQ 和高置信官方 RAG 标成 auto_reply；
        # 社区 RAG、未知问题和人工兜底都在上层分支被拦截。
        return self.config.mode == "auto" and bool(card.source)
