from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .answer_providers import AnswerProvider, AnswerProviderChain
from .knowledge import FAQItem, KnowledgeBase


@dataclass(frozen=True)
class AnswerResult:
    action: str
    reply: str
    intent: str = ""
    source: str = ""
    reason: str = ""
    confidence: float = 0.0
    generation_mode: str = ""
    generation_model: str = ""
    generation_error: str = ""


class AnswerEngine:
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        today: date | None = None,
        rag_retriever=None,
        rag_answer_generator=None,
        providers: list[AnswerProvider] | None = None,
    ):
        self.knowledge_base = knowledge_base
        self.today = today or date.today()
        self.rag_retriever = rag_retriever
        self.rag_answer_generator = rag_answer_generator
        self.provider_chain = AnswerProviderChain(providers) if providers is not None else None

    def answer(self, text: str) -> AnswerResult:
        if self.provider_chain is not None:
            return self.provider_chain.answer(text)

        fallback = self._human_fallback(text)
        if fallback:
            return fallback

        item, confidence = self._retrieve(text)
        if item is not None and confidence >= 0.55 and item.auto_reply:
            if item.is_valid_on(self.today):
                return self._faq_answer(item, confidence, item.answer)
            if item.expired_answer:
                return self._faq_answer(item, confidence, item.expired_answer)

        rag_result = self._retrieve_from_rag(text)
        if rag_result is not None:
            reply = rag_result.reply
            generation_mode = (
                "rag_community"
                if rag_result.trust_level == "community"
                else "rag_fallback"
            )
            generation_model = ""
            generation_error = ""
            if (
                rag_result.trust_level == "official"
                and rag_result.is_strong
                and self.rag_answer_generator is not None
                and rag_result.chunks
            ):
                generated = self.rag_answer_generator.generate(text, rag_result)
                generation_model = generated.model
                generation_error = generated.error
                if generated.status == "generated":
                    reply = generated.answer
                    generation_mode = "rag_ai"
            return AnswerResult(
                action="auto_reply" if rag_result.is_strong else "suggested_reply",
                intent="rag.document",
                reply=reply,
                source=rag_result.source,
                confidence=rag_result.confidence,
                generation_mode=generation_mode,
                generation_model=generation_model,
                generation_error=generation_error,
            )
        return self._needs_info()

    @staticmethod
    def _faq_answer(item: FAQItem, confidence: float, reply: str) -> AnswerResult:
        return AnswerResult(
            action="auto_reply",
            intent=item.intent,
            reply=reply,
            source=f"{item.source}（{item.source_date}，最后更新 {item.last_updated}）",
            confidence=confidence,
            generation_mode="faq",
        )

    def _retrieve_from_rag(self, text: str):
        if self.rag_retriever is None:
            return None
        return self.rag_retriever.retrieve(text)

    def _retrieve(self, text: str) -> tuple[FAQItem | None, float]:
        normalized = self._normalize(text)
        best_item: FAQItem | None = None
        best_score = 0.0
        for item in self.knowledge_base.items:
            candidates = [item.question, *item.question_aliases]
            score = 0.0
            for candidate in candidates:
                candidate_normalized = self._normalize(candidate)
                if not candidate_normalized:
                    continue
                if normalized == candidate_normalized:
                    score = max(score, 1.0)
                elif candidate_normalized in normalized or normalized in candidate_normalized:
                    score = max(score, 0.9)

            keyword_hits = sum(1 for keyword in item.keywords if keyword and keyword in text)
            if item.keywords:
                score = max(score, min(0.85, keyword_hits / len(item.keywords)))

            if score > best_score:
                best_score = score
                best_item = item
        return best_item, best_score

    def _human_fallback(self, text: str) -> AnswerResult | None:
        if self._contains_any(text, ["录取结果", "面试结果", "报名状态", "我被录取", "查下", "查一下面试", "入营名单"]):
            return AnswerResult(
                action="human_fallback",
                reason="personal_status",
                reply="这个问题涉及个人报名状态、录取结果或面试结果，需要由组委会人工确认，agent 不会在群内自动查询或判断。",
                generation_mode="human_fallback",
            )
        if "作业" in text and self._contains_any(text, ["答案", "直接帮我", "代写", "代码跑不通", "debug", "改出答案"]):
            return AnswerResult(
                action="human_fallback",
                reason="technical_assignment",
                reply="这个问题涉及技术作业的具体答案、代码 debug 或评分边界，需要转给课程助教或导师处理，agent 只提供规则说明和资料导航。",
                generation_mode="human_fallback",
            )
        if self._contains_any(text, ["生病", "受伤", "安全", "突发", "冲突", "投诉"]):
            return AnswerResult(
                action="human_fallback",
                reason="safety",
                reply="这个问题可能涉及医疗、安全、突发事件或投诉争议，需要立即转人工处理。",
                generation_mode="human_fallback",
            )
        return None

    @staticmethod
    def _needs_info() -> AnswerResult:
        return AnswerResult(
            action="needs_info",
            reply="这个问题当前资料还没有明确说明，建议等待官方咨询群后续通知，或联系组委会确认。建议将这个问题标记为待补充 FAQ，等组委会确认后再更新知识库。",
            reason="unknown",
            generation_mode="needs_info",
        )

    @staticmethod
    def _normalize(text: str) -> str:
        return "".join(text.lower().split()).strip("？?。.")

    @staticmethod
    def _contains_any(text: str, needles: list[str]) -> bool:
        return any(needle in text for needle in needles)
