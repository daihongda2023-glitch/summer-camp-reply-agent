import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.rag_embeddings import StaticEmbeddingProvider
from summer_camp_agent.rag_index import build_rag_index, load_rag_index
from summer_camp_agent.rag_retriever import RagRetriever


class RagRetrieverTest(unittest.TestCase):
    def test_retriever_returns_answer_when_similarity_is_high(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            index = root / "index"
            documents.mkdir()
            (documents / "handbook.md").write_text(
                "# 线下手册\n\n## 住宿安排\n\n活动期间住宿由主办方统一安排。",
                encoding="utf-8",
            )
            build_rag_index(documents, index, StaticEmbeddingProvider(default_embedding=[1.0, 0.0], model="static-model"))
            retriever = RagRetriever(
                load_rag_index(index, expected_model="static-model"),
                StaticEmbeddingProvider(default_embedding=[1.0, 0.0], model="static-model"),
            )

            result = retriever.retrieve("住宿怎么安排？")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(result.confidence, 0.72)
        self.assertIn("同学你好", result.reply)
        self.assertIn("活动期间住宿由主办方统一安排", result.reply)
        self.assertIn("以上信息来自", result.reply)
        self.assertIn("线下手册", result.source)

    def test_retriever_returns_none_when_similarity_is_low(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            index = root / "index"
            documents.mkdir()
            (documents / "handbook.md").write_text("# 线下手册\n\n活动期间住宿由主办方统一安排。", encoding="utf-8")
            build_rag_index(documents, index, StaticEmbeddingProvider(default_embedding=[1.0, 0.0], model="static-model"))
            retriever = RagRetriever(
                load_rag_index(index, expected_model="static-model"),
                StaticEmbeddingProvider(default_embedding=[0.0, 1.0], model="static-model"),
            )

            result = retriever.retrieve("住宿怎么安排？")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
