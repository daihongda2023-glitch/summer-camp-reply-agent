from __future__ import annotations

from dataclasses import dataclass

from .rag_embeddings import EmbeddingProvider
from .rag_index import IndexedChunk, RagIndex, cosine_similarity


DEFAULT_TOP_K = 4
DEFAULT_MIN_SIMILARITY = 0.72
DEFAULT_STRONG_SIMILARITY = 0.82


@dataclass(frozen=True)
class ScoredChunk:
    chunk: IndexedChunk
    score: float


@dataclass(frozen=True)
class RagSearchResult:
    reply: str
    source: str
    confidence: float
    chunks: list[ScoredChunk]
    is_strong: bool
    trust_level: str = "official"
    source_url: str = ""


class RagRetriever:
    def __init__(
        self,
        rag_index: RagIndex,
        provider: EmbeddingProvider,
        top_k: int = DEFAULT_TOP_K,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        strong_similarity: float = DEFAULT_STRONG_SIMILARITY,
    ):
        self.rag_index = rag_index
        self.provider = provider
        self.top_k = top_k
        self.min_similarity = min_similarity
        self.strong_similarity = strong_similarity

    def retrieve(self, question: str) -> RagSearchResult | None:
        normalized = question.strip()
        if not normalized:
            return None

        query_embedding = self.provider.embed_texts([normalized])[0]
        scored = [
            ScoredChunk(chunk=chunk, score=cosine_similarity(query_embedding, chunk.embedding))
            for chunk in self.rag_index.chunks
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        top_chunks = scored[: self.top_k]
        if not top_chunks or top_chunks[0].score < self.min_similarity:
            return None

        best = top_chunks[0]
        trust_level = best.chunk.metadata.get("trust_level", "official")
        source_url = best.chunk.metadata.get("source_url", "")
        return RagSearchResult(
            reply=format_rag_reply(best.chunk, trust_level=trust_level),
            source=format_rag_source(best.chunk),
            confidence=best.score,
            chunks=top_chunks,
            is_strong=trust_level == "official" and best.score >= self.strong_similarity,
            trust_level=trust_level,
            source_url=source_url,
        )


def format_rag_reply(chunk: IndexedChunk, trust_level: str = "official") -> str:
    body = _body_without_heading(chunk)
    if trust_level == "community":
        return (
            f"同学你好，以下是 GitLink Issue 中的社区经验，仅供排查参考：{body}\n\n"
            f"来源：{format_rag_source(chunk)}。该内容不是官方结论，请联系课程助教确认，并以后续官方答复为准。"
        )
    return (
        f"同学你好，{body}\n\n"
        f"以上信息来自：{format_rag_source(chunk)}。如果后续官方通知更新，请以后续通知为准。"
    )


def format_rag_source(chunk: IndexedChunk) -> str:
    if chunk.heading and chunk.heading != chunk.source_title:
        label = f"{chunk.source_title} / {chunk.heading}"
    else:
        label = chunk.source_title
    source_url = chunk.metadata.get("source_url", "")
    return f"{label}（{source_url}）" if source_url else label


def _body_without_heading(chunk: IndexedChunk) -> str:
    lines = chunk.text.strip().splitlines()
    if lines and lines[0].strip() == chunk.heading.strip():
        lines = lines[1:]
    body = "\n".join(line.strip() for line in lines if line.strip()).strip()
    return body or chunk.text.strip()
