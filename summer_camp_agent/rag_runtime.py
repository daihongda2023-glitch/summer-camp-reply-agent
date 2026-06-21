from __future__ import annotations

from pathlib import Path

from .rag_embeddings import DEFAULT_EMBEDDING_MODEL, OpenAIEmbeddingProvider, RagEmbeddingError, StaticEmbeddingProvider
from .rag_index import CHUNKS_FILE, MANIFEST_FILE, RagIndexError, load_rag_index
from .rag_retriever import RagRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG_INDEX_PATH = PROJECT_ROOT / "data" / "rag" / "index"


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
