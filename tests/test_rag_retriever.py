import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.rag_embeddings import StaticEmbeddingProvider
from summer_camp_agent.rag_index import build_rag_index, load_rag_index
from summer_camp_agent.rag_retriever import RagRetriever


class RagRetrieverTest(unittest.TestCase):
    def _build_retriever_for_document(self, root: Path, trust_level: str) -> RagRetriever:
        documents = root / "documents"
        index = root / "index"
        documents.mkdir()
        (documents / "answer.md").write_text(
            "---\n"
            "source_type: gitlink_issue\n"
            f"trust_level: {trust_level}\n"
            "source_url: https://www.gitlink.org.cn/example/repo/issues/5\n"
            "---\n"
            "# 构建问题\n\n重新安装 cmake 后构建通过。\n",
            encoding="utf-8",
        )
        provider = StaticEmbeddingProvider(default_embedding=[1.0, 0.0], model="static-model")
        build_rag_index(documents, index, provider)
        return RagRetriever(load_rag_index(index, expected_model="static-model"), provider)

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

    def test_official_high_similarity_is_strong_and_includes_url(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._build_retriever_for_document(Path(directory), "official").retrieve("怎么解决构建问题？")

        assert result is not None
        self.assertTrue(result.is_strong)
        self.assertEqual(result.trust_level, "official")
        self.assertIn("https://www.gitlink.org.cn/example/repo/issues/5", result.source)

    def test_community_high_similarity_is_never_strong(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._build_retriever_for_document(Path(directory), "community").retrieve("怎么解决构建问题？")

        assert result is not None
        self.assertFalse(result.is_strong)
        self.assertEqual(result.trust_level, "community")
        self.assertIn("社区经验", result.reply)
        self.assertIn("以后续官方答复为准", result.reply)


if __name__ == "__main__":
    unittest.main()
