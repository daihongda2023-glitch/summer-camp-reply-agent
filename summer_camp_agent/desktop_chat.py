from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .corrections import parse_correction_command, save_local_override
from .engine import AnswerEngine
from .knowledge import KnowledgeBase
from .review import OperatorReview, ReviewCard, save_pending_question


DEFAULT_PENDING_LOG = Path(__file__).resolve().parents[1] / "data" / "pending_questions.jsonl"
DEFAULT_OVERRIDE_PATH = Path(__file__).resolve().parents[1] / "data" / "local_overrides.json"


@dataclass(frozen=True)
class ChatMessage:
    display_text: str
    recommendation: str
    card: ReviewCard


class DesktopChatSession:
    def __init__(
        self,
        pending_log_path: str | Path = DEFAULT_PENDING_LOG,
        override_path: str | Path = DEFAULT_OVERRIDE_PATH,
        enable_corrections: bool = True,
    ):
        self.pending_log_path = Path(pending_log_path)
        self.override_path = Path(override_path)
        self.enable_corrections = enable_corrections
        self.review = self._build_review()
        self.last_card: ReviewCard | None = None
        self.last_user_question: str | None = None

    def ask(self, question: str) -> ChatMessage:
        normalized_question = question.strip()
        correction = parse_correction_command(normalized_question)
        if correction is not None:
            return self._save_correction(normalized_question, correction)

        card = self.review.create_card(normalized_question)
        self.last_card = card
        self.last_user_question = normalized_question
        return ChatMessage(
            display_text=self._format_card(card),
            recommendation=card.recommendation,
            card=card,
        )

    def save_last_pending(self) -> bool:
        if self.last_card is None or self.last_card.recommendation != "mark_pending":
            return False
        save_pending_question(self.last_card, self.pending_log_path)
        return True

    def _save_correction(self, original_command: str, answer: str) -> ChatMessage:
        if not self.enable_corrections:
            return self._system_message(
                original_command,
                "correction_disabled",
                "桌面修正功能已关闭，当前输入不会写入本地覆盖 FAQ。",
            )
        if not self.last_user_question:
            return self._system_message(
                original_command,
                "needs_previous_question",
                "还没有可修正的上一个问题。请先问一个问题，再输入：修正上个问题的回答结果：你的答案",
            )

        save_local_override(self.last_user_question, answer, self.override_path)
        self.review = self._build_review()
        return self._system_message(
            original_command,
            "saved_correction",
            f"已保存修正。下一次问「{self.last_user_question}」时，会优先使用这条本地修正答案。\n\n修正答案：{answer}",
        )

    def _build_review(self) -> OperatorReview:
        return OperatorReview(AnswerEngine(KnowledgeBase.from_default(override_path=self.override_path)))

    @staticmethod
    def _system_message(original_question: str, recommendation: str, text: str) -> ChatMessage:
        card = ReviewCard(
            original_question=original_question,
            recommendation=recommendation,
            available_actions=[],
            action="correction",
            reply=text,
        )
        return ChatMessage(
            display_text=f"建议动作：{recommendation}\n处理类型：correction\n\n{text}",
            recommendation=recommendation,
            card=card,
        )

    @staticmethod
    def _format_card(card: ReviewCard) -> str:
        lines = [
            f"建议动作：{card.recommendation}",
            f"处理类型：{card.action}",
        ]
        if card.intent:
            lines.append(f"意图：{card.intent}")
        if card.reason:
            lines.append(f"原因：{card.reason}")
        if card.source:
            lines.append(f"来源：{card.source}")
        lines.extend(["", card.reply])
        return "\n".join(lines)
