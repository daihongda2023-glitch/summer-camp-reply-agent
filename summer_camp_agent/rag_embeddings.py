from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol


DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"


class RagEmbeddingError(RuntimeError):
    """Embedding 生成失败。"""


class EmbeddingProvider(Protocol):
    model: str

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class StaticEmbeddingProvider:
    def __init__(
        self,
        vectors: dict[str, list[float]] | None = None,
        default_embedding: list[float] | None = None,
        model: str = "static-test-embedding",
    ):
        self.vectors = vectors or {}
        self.default_embedding = default_embedding
        self.model = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            vector = self.vectors.get(text, self.default_embedding)
            if vector is None:
                raise RagEmbeddingError(f"StaticEmbeddingProvider 未配置文本向量：{text}")
            embeddings.append([float(value) for value in vector])
        return embeddings


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_EMBEDDING_MODEL,
        timeout_seconds: int = 30,
    ):
        api_key = api_key.strip()
        if not api_key:
            raise RagEmbeddingError("缺少 OPENAI_API_KEY，请先在环境变量中设置 OpenAI API Key。")
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(
        cls,
        env_var: str = "OPENAI_API_KEY",
        model: str = DEFAULT_EMBEDDING_MODEL,
        timeout_seconds: int = 30,
    ) -> "OpenAIEmbeddingProvider":
        api_key = os.environ.get(env_var, "")
        if not api_key.strip():
            raise RagEmbeddingError(f"缺少 {env_var}，请先在环境变量中设置 OpenAI API Key。")
        return cls(api_key=api_key, model=model, timeout_seconds=timeout_seconds)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": self.model, "input": texts}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            OPENAI_EMBEDDINGS_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise RagEmbeddingError(f"Embedding API 请求失败，HTTP 状态码：{exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RagEmbeddingError("Embedding API 网络连接失败，请检查网络或代理设置。") from exc
        except TimeoutError as exc:
            raise RagEmbeddingError("Embedding API 请求超时，请稍后重试。") from exc

        return _parse_embedding_response(raw_body, expected_count=len(texts))


def _parse_embedding_response(raw_body: str, expected_count: int) -> list[list[float]]:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RagEmbeddingError("Embedding API 返回格式异常：响应不是合法 JSON。") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != expected_count:
        raise RagEmbeddingError("Embedding API 返回格式异常：data 数量与请求不一致。")

    vectors: list[list[float] | None] = [None] * expected_count
    for default_index, item in enumerate(data):
        if not isinstance(item, dict):
            raise RagEmbeddingError("Embedding API 返回格式异常：data 条目不是对象。")
        index = item.get("index", default_index)
        embedding = item.get("embedding")
        if not isinstance(index, int) or index < 0 or index >= expected_count:
            raise RagEmbeddingError("Embedding API 返回格式异常：index 无效。")
        if not isinstance(embedding, list) or not embedding:
            raise RagEmbeddingError("Embedding API 返回格式异常：embedding 不是数字数组。")
        if not all(_is_number(value) for value in embedding):
            raise RagEmbeddingError("Embedding API 返回格式异常：embedding 不是数字数组。")
        vectors[index] = [float(value) for value in embedding]

    if any(vector is None for vector in vectors):
        raise RagEmbeddingError("Embedding API 返回格式异常：缺少部分 embedding。")
    return [vector for vector in vectors if vector is not None]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
