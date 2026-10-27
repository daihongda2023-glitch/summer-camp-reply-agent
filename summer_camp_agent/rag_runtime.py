from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .rag_ai import DEFAULT_OPENAI_BASE_URL, DEFAULT_OPENAI_CHAT_MODEL, OpenAIRagAnswerGenerator, RagAnswerGenerator
from .rag_documents import load_document_chunks
from .rag_embeddings import DEFAULT_EMBEDDING_MODEL, OPENAI_EMBEDDINGS_URL, OpenAIEmbeddingProvider, RagEmbeddingError, StaticEmbeddingProvider
from .rag_index import CHUNKS_FILE, MANIFEST_FILE, RagIndexError, load_rag_index
from .rag_retriever import LocalDocumentRagRetriever, RagRetriever
from .semantic_router import OpenAISemanticAnalyzer, SemanticAnalyzer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG_INDEX_PATH = PROJECT_ROOT / "data" / "rag" / "index"
DEFAULT_RAG_DOCUMENTS_PATH = PROJECT_ROOT / "data" / "rag" / "documents"


def model_status() -> dict[str, str]:
    chat_model = os.environ.get("OPENAI_CHAT_MODEL", "").strip() or DEFAULT_OPENAI_CHAT_MODEL
    chat_base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or DEFAULT_OPENAI_BASE_URL
    return {
        "chat_model": chat_model,
        "chat_base_url": chat_base_url.rstrip("/"),
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "embedding_url": OPENAI_EMBEDDINGS_URL,
        "api_key": "已设置" if os.environ.get("OPENAI_API_KEY", "").strip() else "未设置",
    }


def create_embedding_provider(
    provider_name: str = "openai",
    model: str = DEFAULT_EMBEDDING_MODEL,
    token_env: str = "OPENAI_API_KEY",
):
    if provider_name == "static":
        return StaticEmbeddingProvider(default_embedding=[1.0, 0.0], model=model)
    return OpenAIEmbeddingProvider.from_env(env_var=token_env, model=model)


def load_optional_rag_retriever(
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    provider_name: str = "openai",
    model: str | None = None,
    token_env: str = "OPENAI_API_KEY",
    top_k: int = 4,
) -> RagRetriever | None:
    target = Path(index_path)
    if not (target / MANIFEST_FILE).exists() or not (target / CHUNKS_FILE).exists():
        return None
    try:
        rag_index = load_rag_index(target)
        index_model = str(rag_index.manifest.get("model") or DEFAULT_EMBEDDING_MODEL)
        provider = create_embedding_provider(provider_name=provider_name, model=model or index_model, token_env=token_env)
    except (RagEmbeddingError, RagIndexError):
        return None
    return RagRetriever(rag_index, provider, top_k=top_k)


def load_default_rag_answer_generator() -> RagAnswerGenerator | None:
    return OpenAIRagAnswerGenerator.from_env()


def load_default_semantic_analyzer() -> SemanticAnalyzer | None:
    return OpenAISemanticAnalyzer.from_env()


@lru_cache(maxsize=1)
def load_default_rag_retriever() -> LocalDocumentRagRetriever | None:
    chunks = load_document_chunks(DEFAULT_RAG_DOCUMENTS_PATH)
    if not chunks:
        return None
    return LocalDocumentRagRetriever(chunks)
