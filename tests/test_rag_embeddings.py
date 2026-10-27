import json
import os
import unittest
from unittest.mock import patch

from summer_camp_agent.rag_embeddings import (
    OpenAIEmbeddingProvider,
    RagEmbeddingError,
    StaticEmbeddingProvider,
)


class RagEmbeddingsTest(unittest.TestCase):
    def test_static_provider_returns_exact_vectors(self):
        provider = StaticEmbeddingProvider({"报名入口": [1.0, 0.0]}, default_embedding=[0.0, 1.0])

        self.assertEqual(provider.embed_texts(["报名入口", "住宿安排"]), [[1.0, 0.0], [0.0, 1.0]])

    def test_openai_provider_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RagEmbeddingError, "缺少 OPENAI_API_KEY"):
                OpenAIEmbeddingProvider.from_env()

    def test_openai_provider_sends_embedding_request_and_parses_vectors(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "object": "list",
                        "model": "text-embedding-3-small",
                        "data": [
                            {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
                            {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
                        ],
                    }
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return FakeResponse()

        provider = OpenAIEmbeddingProvider(api_key="test-key")
        with patch("urllib.request.urlopen", fake_urlopen):
            vectors = provider.embed_texts(["报名入口", "住宿安排"])

        self.assertEqual(captured["url"], "https://api.openai.com/v1/embeddings")
        self.assertEqual(captured["body"], {"model": "text-embedding-3-small", "input": ["报名入口", "住宿安排"]})
        self.assertEqual(captured["authorization"], "Bearer test-key")
        self.assertEqual(captured["timeout"], 30)
        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])

    def test_openai_provider_rejects_unexpected_response_shape(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"data":[{"embedding":"bad"}]}'

        provider = OpenAIEmbeddingProvider(api_key="test-key")
        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(RagEmbeddingError, "Embedding API 返回格式异常"):
                provider.embed_texts(["报名入口"])


if __name__ == "__main__":
    unittest.main()
