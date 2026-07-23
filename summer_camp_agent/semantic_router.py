from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .rag_ai import DEFAULT_OPENAI_BASE_URL, DEFAULT_OPENAI_CHAT_MODEL


MAX_CANONICAL_QUESTION_CHARS = 200
MAX_RAG_QUERIES = 3
MAX_RAG_QUERY_CHARS = 120
SEMANTIC_FAQ_THRESHOLD = 0.80
SEMANTIC_RAG_THRESHOLD = 0.85
UNSAFE_QUERY_PATTERN = re.compile(
    r"忽略(?:之前|以上|所有)|直接回答|系统提示|system\s+prompt|ignore\s+(?:all\s+)?previous",
    re.IGNORECASE,
)

SYSTEM_INSTRUCTIONS = """你是夏令营咨询系统的语义路由器，只做意图识别和知识目录选择。
只能选择输入目录中真实存在的 FAQ ID 或 RAG 文档块 ID；不要回答学生问题，不要补充事实。
将自然问法改写成最多三条简短检索问题。证据可能不足时可以不给候选，并说明需要人工。
输出必须严格符合给定 JSON Schema，不要输出 Markdown 或分析过程。"""


@dataclass(frozen=True)
class SemanticCatalog:
    faq_items: list[dict[str, object]]
    rag_items: list[dict[str, str]]


@dataclass(frozen=True)
class SemanticAnalysisResult:
    status: str
    canonical_question: str = ""
    intent: str = ""
    faq_candidate_ids: list[str] = field(default_factory=list)
    rag_candidate_ids: list[str] = field(default_factory=list)
    rag_queries: list[str] = field(default_factory=list)
    semantic_confidence: float = 0.0
    requires_human: bool = False
    reason: str = ""
    model: str = ""
    error: str = ""


class SemanticAnalyzer(Protocol):
    model: str

    def analyze(
        self,
        question: str,
        catalog: SemanticCatalog,
    ) -> SemanticAnalysisResult:
        raise NotImplementedError


class OpenAISemanticAnalyzer:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_CHAT_MODEL,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        timeout_seconds: int = 15,
    ):
        self._api_key = api_key.strip()
        self.model = model.strip() or DEFAULT_OPENAI_CHAT_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> OpenAISemanticAnalyzer | None:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            model=os.environ.get("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_CHAT_MODEL),
            base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )

    def analyze(
        self,
        question: str,
        catalog: SemanticCatalog,
    ) -> SemanticAnalysisResult:
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(
                _request_payload(self.model, question, catalog),
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
            payload = _parse_response(raw_body)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            return SemanticAnalysisResult(
                "unavailable",
                model=self.model,
                error=_error_code(exc),
            )
        except (ValueError, UnicodeDecodeError):
            return SemanticAnalysisResult(
                "invalid",
                model=self.model,
                error="invalid_response",
            )

        error = _validation_error(payload, catalog)
        if error:
            return SemanticAnalysisResult(
                "invalid",
                model=self.model,
                error=error,
            )
        return SemanticAnalysisResult(
            "analyzed",
            canonical_question=payload["canonical_question"].strip(),
            intent=payload["intent"].strip(),
            faq_candidate_ids=_unique_strings(payload["faq_candidate_ids"]),
            rag_candidate_ids=_unique_strings(payload["rag_candidate_ids"]),
            rag_queries=[query.strip() for query in payload["rag_queries"]],
            semantic_confidence=float(payload["semantic_confidence"]),
            requires_human=payload["requires_human"],
            reason=payload["reason"].strip(),
            model=self.model,
        )


def _request_payload(
    model: str,
    question: str,
    catalog: SemanticCatalog,
) -> dict[str, object]:
    catalog_payload = {
        "faq_items": catalog.faq_items,
        "rag_items": catalog.rag_items,
    }
    return {
        "model": model,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": (
            f"学生问题：\n{question.strip()}\n\n"
            f"可选知识目录：\n{json.dumps(catalog_payload, ensure_ascii=False)}"
        ),
        "reasoning": {"effort": "none"},
        "max_output_tokens": 600,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "semantic_route",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "canonical_question": {"type": "string"},
                        "intent": {"type": "string"},
                        "faq_candidate_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "rag_candidate_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "rag_queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": MAX_RAG_QUERIES,
                        },
                        "semantic_confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "requires_human": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "canonical_question",
                        "intent",
                        "faq_candidate_ids",
                        "rag_candidate_ids",
                        "rag_queries",
                        "semantic_confidence",
                        "requires_human",
                        "reason",
                    ],
                    "additionalProperties": False,
                },
            }
        },
    }


def _parse_response(raw_body: str) -> dict[str, object]:
    response = json.loads(raw_body)
    output = response.get("output") if isinstance(response, dict) else None
    if not isinstance(output, list):
        raise ValueError("Responses API 缺少 output。")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            payload = json.loads(str(part.get("text") or ""))
            if not isinstance(payload, dict):
                raise ValueError("Responses API 语义输出不是对象。")
            return payload
    raise ValueError("Responses API 缺少 output_text。")


def _validation_error(
    payload: dict[str, object],
    catalog: SemanticCatalog,
) -> str:
    required_strings = ("canonical_question", "intent", "reason")
    if any(not isinstance(payload.get(key), str) for key in required_strings):
        return "invalid_response"
    required_lists = ("faq_candidate_ids", "rag_candidate_ids", "rag_queries")
    if any(not _is_string_list(payload.get(key)) for key in required_lists):
        return "invalid_response"
    confidence = payload.get("semantic_confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return "invalid_response"
    if not isinstance(payload.get("requires_human"), bool):
        return "invalid_response"

    canonical_question = str(payload["canonical_question"]).strip()
    if not canonical_question or len(canonical_question) > MAX_CANONICAL_QUESTION_CHARS:
        return "canonical_question_too_long"
    if not str(payload["intent"]).strip():
        return "invalid_response"
    if not 0 <= float(confidence) <= 1:
        return "invalid_semantic_confidence"

    faq_ids = {
        str(item.get("id") or "").strip()
        for item in catalog.faq_items
        if isinstance(item, dict)
    }
    rag_ids = {
        str(item.get("id") or "").strip()
        for item in catalog.rag_items
        if isinstance(item, dict)
    }
    selected_faq_ids = _unique_strings(payload["faq_candidate_ids"])
    selected_rag_ids = _unique_strings(payload["rag_candidate_ids"])
    if any(candidate not in faq_ids for candidate in selected_faq_ids):
        return "invalid_catalog_candidate"
    if any(candidate not in rag_ids for candidate in selected_rag_ids):
        return "invalid_catalog_candidate"

    rag_queries = payload["rag_queries"]
    if len(rag_queries) > MAX_RAG_QUERIES:
        return "too_many_rag_queries"
    for query in rag_queries:
        normalized = query.strip()
        if len(normalized) > MAX_RAG_QUERY_CHARS:
            return "rag_query_too_long"
        if "\n" in query or UNSAFE_QUERY_PATTERN.search(normalized):
            return "unsafe_rag_query"
    return ""


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _unique_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip()))


def _error_code(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.HTTPError):
        if _openai_error_code(exc) == "insufficient_quota":
            return "insufficient_quota"
        return f"http_{exc.code}"
    return "network_error"


def _openai_error_code(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, ValueError):
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return ""
    code = error.get("code") or error.get("type")
    return code if isinstance(code, str) else ""
