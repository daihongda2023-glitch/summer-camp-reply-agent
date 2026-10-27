from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import AnswerResult


@dataclass(frozen=True)
class ProviderAnswer:
    result: "AnswerResult | None"
    reason: str = ""

    @classmethod
    def hit(cls, result: "AnswerResult") -> "ProviderAnswer":
        return cls(result=result)

    @classmethod
    def miss(cls, reason: str = "") -> "ProviderAnswer":
        return cls(result=None, reason=reason)


class AnswerProvider(Protocol):
    name: str

    def answer(self, text: str) -> ProviderAnswer:
        ...


class AnswerProviderChain:
    def __init__(self, providers: list[AnswerProvider]):
        self.providers = providers

    def answer(self, text: str) -> "AnswerResult":
        for provider in self.providers:
            answer = provider.answer(text)
            if answer.result is not None:
                return answer.result
        return self._default_needs_info()

    @staticmethod
    def _default_needs_info() -> "AnswerResult":
        from .engine import AnswerEngine

        return AnswerEngine._needs_info()
