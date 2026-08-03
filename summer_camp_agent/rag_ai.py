from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .rag_retriever import RagSearchResult


DEFAULT_OPENAI_CHAT_MODEL = "deepseek-v4-pro"
DEFAULT_OPENAI_BASE_URL = "https://api.deepseek.com"
MAX_GENERATED_REPLY_CHARS = 600
URL_PATTERN = re.compile(r"https?://[^\s，。；、）)\]}>\"']+")

SYSTEM_INSTRUCTIONS = """你是夏令营咨询群回复助手。只能依据用户提供的官方证据回答。
不得补充证据中没有的日期、数字、链接、规则或承诺；证据不足时将 grounded 设为 false。
面向学生直接作答，使用简洁自然的中文，不输出 Markdown 标题、代码块或内部分析过程。
只输出 JSON 对象，且只能包含 answer 和 grounded 两个字段；answer 必须是字符串，grounded 必须是布尔值。"""


@dataclass(frozen=True)
class RagGenerationResult:
    status: str
    answer: str = ""
    model: str = ""
    error: str = ""


class RagAnswerGenerator(Protocol):
    model: str

    def generate(self, question: str, rag_result: RagSearchResult) -> RagGenerationResult:
        ...


class OpenAIRagAnswerGenerator:
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
    def from_env(cls) -> OpenAIRagAnswerGenerator | None:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            model=os.environ.get("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_CHAT_MODEL),
            base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )

    def generate(self, question: str, rag_result: RagSearchResult) -> RagGenerationResult:
        evidence = _build_evidence(rag_result)
        if not evidence:
            return RagGenerationResult("invalid", model=self.model, error="missing_evidence")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(
                _request_payload(self.model, question, evidence),
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
            answer, grounded = _parse_response(raw_body)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            return RagGenerationResult(
                "unavailable",
                model=self.model,
                error=_error_code(exc),
            )
        except (ValueError, UnicodeDecodeError):
            return RagGenerationResult(
                "invalid",
                model=self.model,
                error="invalid_response",
            )
        if not grounded:
            return RagGenerationResult("invalid", model=self.model, error="not_grounded")
        validation_error = validate_generated_answer(
            answer,
            evidence,
            rag_result.source_url,
        )
        if validation_error:
            return RagGenerationResult(
                "invalid",
                model=self.model,
                error=validation_error,
            )
        return RagGenerationResult(
            "generated",
            answer=answer.strip(),
            model=self.model,
        )


def _build_evidence(rag_result: RagSearchResult) -> str:
    if not rag_result.chunks:
        return ""
    best = rag_result.chunks[0].chunk
    if best.metadata.get("trust_level", "official") != "official":
        return ""
    return (
        f"标题：{best.heading or best.source_title}\n"
        f"正文：{best.text.strip()}\n"
        f"来源：{rag_result.source}\n"
        f"来源地址：{rag_result.source_url}"
    ).strip()


def _request_payload(model: str, question: str, evidence: str) -> dict[str, object]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {
                "role": "user",
                "content": (
                    f"学生问题：\n{question.strip()}\n\n"
                    f"官方证据：\n{evidence}"
                ),
            },
        ],
        "thinking": {"type": "disabled"},
        "max_tokens": 500,
        "stream": False,
        "response_format": {"type": "json_object"},
    }


def _parse_response(raw_body: str) -> tuple[str, bool]:
    payload = json.loads(raw_body)
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list):
        raise ValueError("DeepSeek Chat Completions API 缺少 choices。")
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        parsed = json.loads(content)
        answer = parsed.get("answer") if isinstance(parsed, dict) else None
        grounded = parsed.get("grounded") if isinstance(parsed, dict) else None
        if not isinstance(answer, str) or not isinstance(grounded, bool):
            raise ValueError("DeepSeek 结构化输出字段类型错误。")
        return answer, grounded
    raise ValueError("DeepSeek Chat Completions API 缺少消息内容。")


def validate_generated_answer(
    answer: str,
    evidence: str,
    source_url: str = "",
) -> str:
    normalized = answer.strip()
    if not normalized:
        return "empty_answer"
    if len(normalized) > MAX_GENERATED_REPLY_CHARS:
        return "answer_too_long"
    allowed_text = f"{evidence}\n{source_url}"
    if any(url not in allowed_text for url in URL_PATTERN.findall(normalized)):
        return "unsupported_url"
    if normalized.startswith("{") or "```" in normalized:
        return "invalid_wrapper"
    return ""


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
