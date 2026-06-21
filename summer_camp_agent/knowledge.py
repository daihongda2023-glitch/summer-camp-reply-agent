from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .corrections import load_local_override_dicts


class KnowledgeValidationError(ValueError):
    """知识库条目不满足自动回复安全要求。"""


@dataclass(frozen=True)
class FAQItem:
    id: str
    stage: str
    intent: str
    question: str
    question_aliases: list[str]
    answer: str
    source: str
    source_date: str
    last_updated: str
    valid_until: str
    auto_reply: bool
    needs_human_fallback: bool
    human_fallback_reason: str
    owner: str
    keywords: list[str]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FAQItem":
        required = [
            "id",
            "stage",
            "intent",
            "question",
            "question_aliases",
            "answer",
            "source",
            "source_date",
            "last_updated",
            "valid_until",
            "auto_reply",
            "needs_human_fallback",
            "human_fallback_reason",
            "owner",
        ]
        for field in required:
            if field not in raw:
                raise KnowledgeValidationError(f"{field} is required")

        item = cls(
            id=str(raw["id"]).strip(),
            stage=str(raw["stage"]).strip(),
            intent=str(raw["intent"]).strip(),
            question=str(raw["question"]).strip(),
            question_aliases=[str(value).strip() for value in raw["question_aliases"]],
            answer=str(raw["answer"]).strip(),
            source=str(raw["source"]).strip(),
            source_date=str(raw["source_date"]).strip(),
            last_updated=str(raw["last_updated"]).strip(),
            valid_until=str(raw["valid_until"]).strip(),
            auto_reply=bool(raw["auto_reply"]),
            needs_human_fallback=bool(raw["needs_human_fallback"]),
            human_fallback_reason=str(raw["human_fallback_reason"]).strip(),
            owner=str(raw["owner"]).strip(),
            keywords=[str(value).strip() for value in raw.get("keywords", [])],
        )
        item.validate()
        return item

    def validate(self) -> None:
        if not self.id:
            raise KnowledgeValidationError("id is required")
        if not self.intent:
            raise KnowledgeValidationError("intent is required")
        if not isinstance(self.question_aliases, list):
            raise KnowledgeValidationError("question_aliases must be a list")
        if self.auto_reply:
            for field_name in ("source", "source_date", "last_updated"):
                if not getattr(self, field_name):
                    raise KnowledgeValidationError(f"{field_name} is required for auto_reply")
            if not self.answer:
                raise KnowledgeValidationError("answer is required for auto_reply")
        if not self.auto_reply and not self.human_fallback_reason:
            raise KnowledgeValidationError("human_fallback_reason is required when auto_reply is false")
        if self.valid_until:
            self._parse_date(self.valid_until, "valid_until")

    def is_valid_on(self, today: date) -> bool:
        if not self.valid_until:
            return True
        return today <= self._parse_date(self.valid_until, "valid_until")

    @staticmethod
    def _parse_date(value: str, field_name: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise KnowledgeValidationError(f"{field_name} must be YYYY-MM-DD") from exc


class KnowledgeBase:
    def __init__(self, items: list[FAQItem]):
        self.items = items

    @classmethod
    def from_json(cls, path: str | Path) -> "KnowledgeBase":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise KnowledgeValidationError("knowledge file must contain a list")
        return cls([FAQItem.from_dict(item) for item in raw])

    @classmethod
    def from_default(cls, override_path: str | Path | None = None) -> "KnowledgeBase":
        root = Path(__file__).resolve().parents[1]
        base = cls.from_json(root / "data" / "faq.json")
        if override_path is None:
            override_path = root / "data" / "local_overrides.json"
        override_items = [FAQItem.from_dict(item) for item in load_local_override_dicts(override_path)]
        return cls([*override_items, *base.items])
