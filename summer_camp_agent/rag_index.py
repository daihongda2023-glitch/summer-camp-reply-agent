from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .rag_documents import DocumentChunk, load_document_chunks
from .rag_embeddings import EmbeddingProvider


SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
CHUNKS_FILE = "chunks.jsonl"


class RagIndexError(RuntimeError):
    """RAG 本地索引不可用。"""


@dataclass(frozen=True)
class RagIndexSummary:
    index_path: Path
    manifest_path: Path
    chunks_path: Path
    chunk_count: int


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: str
    source_path: str
    source_title: str
    source_sha256: str
    heading: str
    text: str
    embedding: list[float]
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_document_chunk(cls, chunk: DocumentChunk, embedding: list[float]) -> "IndexedChunk":
        return cls(
            chunk_id=chunk.chunk_id,
            source_path=chunk.source_path,
            source_title=chunk.source_title,
            source_sha256=chunk.source_sha256,
            heading=chunk.heading,
            text=chunk.text,
            embedding=[float(value) for value in embedding],
            metadata=dict(chunk.metadata),
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "IndexedChunk":
        required = ["chunk_id", "source_path", "source_title", "source_sha256", "heading", "text", "embedding"]
        for field_name in required:
            if field_name not in raw:
                raise RagIndexError(f"索引 chunk 缺少字段：{field_name}")
        embedding = raw["embedding"]
        if not isinstance(embedding, list) or not all(isinstance(value, (int, float)) for value in embedding):
            raise RagIndexError("索引 chunk 的 embedding 必须是数字数组。")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise RagIndexError("索引 chunk 的 metadata 必须是对象。")
        return cls(
            chunk_id=str(raw["chunk_id"]),
            source_path=str(raw["source_path"]),
            source_title=str(raw["source_title"]),
            source_sha256=str(raw["source_sha256"]),
            heading=str(raw["heading"]),
            text=str(raw["text"]),
            embedding=[float(value) for value in embedding],
            metadata={str(key): str(value) for key, value in metadata.items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_path": self.source_path,
            "source_title": self.source_title,
            "source_sha256": self.source_sha256,
            "heading": self.heading,
            "text": self.text,
            "embedding": self.embedding,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class RagIndex:
    manifest: dict[str, Any]
    chunks: list[IndexedChunk]


def build_rag_index(
    documents_path: str | Path,
    index_path: str | Path,
    provider: EmbeddingProvider,
) -> RagIndexSummary:
    documents_root = Path(documents_path)
    target = Path(index_path)
    chunks = load_document_chunks(documents_root)
    if not chunks:
        raise RagIndexError("没有找到可索引的正式资料，请检查 documents 目录。")

    embeddings = provider.embed_texts([chunk.text for chunk in chunks])
    if len(embeddings) != len(chunks):
        raise RagIndexError("Embedding 数量与 chunk 数量不一致。")

    indexed_chunks = [
        IndexedChunk.from_document_chunk(chunk, embedding)
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / MANIFEST_FILE
    chunks_path = target / CHUNKS_FILE
    manifest = _build_manifest(documents_root, provider.model, indexed_chunks)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in indexed_chunks:
            handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
    return RagIndexSummary(
        index_path=target,
        manifest_path=manifest_path,
        chunks_path=chunks_path,
        chunk_count=len(indexed_chunks),
    )


def load_rag_index(index_path: str | Path, expected_model: str | None = None) -> RagIndex:
    target = Path(index_path)
    manifest_path = target / MANIFEST_FILE
    chunks_path = target / CHUNKS_FILE
    if not manifest_path.exists() or not chunks_path.exists():
        raise RagIndexError("RAG 索引不存在，请先运行 rag-index。")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RagIndexError("RAG 索引清单格式异常。") from exc
    if not isinstance(manifest, dict):
        raise RagIndexError("RAG 索引清单格式异常。")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RagIndexError("RAG 索引版本不兼容，请重新生成索引。")
    if expected_model and manifest.get("model") != expected_model:
        raise RagIndexError("RAG 索引模型不一致，请重新生成索引。")

    chunks: list[IndexedChunk] = []
    try:
        with chunks_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        raise RagIndexError("RAG chunk 格式异常。")
                    chunks.append(IndexedChunk.from_dict(raw))
    except json.JSONDecodeError as exc:
        raise RagIndexError("RAG chunk 文件格式异常。") from exc
    if not chunks:
        raise RagIndexError("RAG 索引为空，请重新生成索引。")
    return RagIndex(manifest=manifest, chunks=chunks)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _build_manifest(documents_root: Path, model: str, chunks: list[IndexedChunk]) -> dict[str, Any]:
    source_files = {
        chunk.source_path: chunk.source_sha256
        for chunk in chunks
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "local",
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(documents_root),
        "chunk_count": len(chunks),
        "source_files": [
            {"path": path, "sha256": sha256}
            for path, sha256 in sorted(source_files.items())
        ],
    }
