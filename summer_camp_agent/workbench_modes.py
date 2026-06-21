from __future__ import annotations

from .review import ReviewCard
from .workbench_models import GroupConfig, ReplyDecision, TriggerDecision


AUTO_REPLY_THRESHOLD = 0.9


class ReplyModeController:
    def __init__(self, config: GroupConfig, auto_reply_threshold: float = AUTO_REPLY_THRESHOLD):
        self.config = config
        self.auto_reply_threshold = auto_reply_threshold

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
        return (
            self.config.mode == "auto"
            and bool(card.source)
            and card.confidence >= self.auto_reply_threshold
            and card.intent in set(self.config.auto_reply_intents)
        )
