from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from .rag_documents import DocumentChunk
from .rag_embeddings import EmbeddingProvider
from .rag_index import IndexedChunk, RagIndex, cosine_similarity


DEFAULT_TOP_K = 4
DEFAULT_MIN_SIMILARITY = 0.72
DEFAULT_STRONG_SIMILARITY = 0.82
DEFAULT_SEMANTIC_STRONG_CONFIDENCE = 0.85


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
    retrieval_mode: str = "local"
    lexical_confidence: float = 0.0
    semantic_confidence: float = 0.0
    retrieval_query: str = ""


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
            lexical_confidence=best.score,
            retrieval_query=question.strip(),
        )


class LocalDocumentRagRetriever:
    """无需外部 Embedding 服务的本地文档检索器。"""

    def __init__(
        self,
        chunks: list[DocumentChunk],
        top_k: int = DEFAULT_TOP_K,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        strong_similarity: float = DEFAULT_STRONG_SIMILARITY,
    ):
        self.chunks = [IndexedChunk.from_document_chunk(chunk, []) for chunk in chunks]
        self.top_k = top_k
        self.min_similarity = min_similarity
        self.strong_similarity = strong_similarity

    def retrieve(self, question: str) -> RagSearchResult | None:
        normalized = _normalize_for_local_search(question)
        if not normalized:
            return None

        scored = [
            ScoredChunk(chunk=chunk, score=_local_similarity(question, chunk))
            for chunk in self.chunks
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
            lexical_confidence=best.score,
            retrieval_query=normalized,
        )

    def retrieve_semantic(
        self,
        question: str,
        candidate_ids: list[str],
        semantic_confidence: float,
    ) -> RagSearchResult | None:
        unique_ids = {
            candidate_id.strip()
            for candidate_id in candidate_ids
            if candidate_id.strip()
        }
        if (
            len(unique_ids) != 1
            or semantic_confidence < DEFAULT_SEMANTIC_STRONG_CONFIDENCE
            or semantic_confidence > 1
        ):
            return None
        candidate_id = next(iter(unique_ids))
        matches = [chunk for chunk in self.chunks if chunk.chunk_id == candidate_id]
        if len(matches) != 1:
            return None

        chunk = matches[0]
        trust_level = chunk.metadata.get("trust_level", "official")
        source_url = chunk.metadata.get("source_url", "")
        lexical_confidence = _local_similarity(question, chunk)
        return RagSearchResult(
            reply=format_rag_reply(chunk, trust_level=trust_level),
            source=format_rag_source(chunk),
            confidence=semantic_confidence,
            chunks=[ScoredChunk(chunk=chunk, score=semantic_confidence)],
            is_strong=trust_level == "official",
            trust_level=trust_level,
            source_url=source_url,
            retrieval_mode="semantic",
            lexical_confidence=lexical_confidence,
            semantic_confidence=semantic_confidence,
            retrieval_query=question.strip(),
        )


def format_rag_reply(chunk: IndexedChunk, trust_level: str = "official") -> str:
    body = _body_without_heading(chunk)
    if trust_level == "community":
        return (
            f"同学你好，以下是 GitLink Issue 中的社区经验，仅供排查参考：{body}\n\n"
            f"来源：{format_rag_source(chunk)}。该内容不是官方结论，请联系课程助教确认，并以后续官方答复为准。"
        )
    if chunk.metadata.get("source_type") == "gitlink_issue":
        return _body_without_heading_preserving_spacing(chunk)
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


def _body_without_heading_preserving_spacing(chunk: IndexedChunk) -> str:
    lines = chunk.text.strip().splitlines()
    if lines and lines[0].strip() == chunk.heading.strip():
        lines = lines[1:]
    body = "\n".join(lines).strip()
    return body or chunk.text.strip()


def _local_similarity(question: str, chunk: IndexedChunk) -> float:
    raw_question = question
    question = _normalize_for_local_search(question)
    heading = _normalize_for_local_search(chunk.heading)
    text = _normalize_for_local_search(chunk.text)
    if not heading and not text:
        return 0.0
    if question == heading:
        return 1.0
    if question in heading or heading in question:
        return 0.96
    if question in text:
        return 0.94

    heading_ratio = SequenceMatcher(None, question, heading).ratio() if heading else 0.0
    question_pairs = _character_pairs(question)
    heading_pairs = _character_pairs(heading)
    text_pairs = _character_pairs(text)
    heading_coverage = _coverage(question_pairs, heading_pairs)
    text_coverage = _coverage(question_pairs, text_pairs)
    technical_score = _technical_identifier_score(raw_question, chunk.heading)
    return min(
        0.93,
        max(
            heading_ratio,
            heading_coverage * 0.92,
            text_coverage * 0.88,
            technical_score,
        ),
    )


def _normalize_for_local_search(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text.lower())


def _character_pairs(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[index : index + 2] for index in range(len(text) - 1)}


def _coverage(question_pairs: set[str], candidate_pairs: set[str]) -> float:
    if not question_pairs:
        return 0.0
    return len(question_pairs & candidate_pairs) / len(question_pairs)


def _technical_identifier_score(question: str, heading: str) -> float:
    question_tokens = _technical_identifiers(question)
    heading_tokens = _technical_identifiers(heading)
    shared = question_tokens & heading_tokens
    shared_chinese_pairs = _chinese_pairs(question) & _chinese_pairs(heading)
    if len(shared) >= 3:
        return 0.90
    if len(shared) >= 2 and shared_chinese_pairs:
        return 0.90
    if len(shared) == 1 and shared_chinese_pairs:
        return 0.76
    return 0.0


def _technical_identifiers(text: str) -> set[str]:
    versions = re.findall(r"\d+(?:\.\d+)+", text.lower())
    words = re.findall(r"[a-z][a-z0-9+._-]*", text.lower())
    return {token.strip("._-") for token in [*versions, *words] if token.strip("._-")}


def _chinese_pairs(text: str) -> set[str]:
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    return _character_pairs(chinese)
