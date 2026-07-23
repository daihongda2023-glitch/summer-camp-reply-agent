import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from summer_camp_agent.rag_embeddings import StaticEmbeddingProvider
from summer_camp_agent.rag_index import build_rag_index, load_rag_index
from summer_camp_agent.rag_documents import load_document_chunks
from summer_camp_agent.rag_retriever import LocalDocumentRagRetriever, RagRetriever
from summer_camp_agent.rag_runtime import load_default_rag_answer_generator


class RagRetrieverTest(unittest.TestCase):
    def test_default_rag_answer_generator_uses_openai_environment(self):
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_CHAT_MODEL": "gpt-test",
                "OPENAI_BASE_URL": "https://example.test/v1",
            },
            clear=True,
        ):
            generator = load_default_rag_answer_generator()

        self.assertIsNotNone(generator)
        assert generator is not None
        self.assertEqual(generator.model, "gpt-test")
        self.assertEqual(generator.base_url, "https://example.test/v1")

    def test_default_rag_answer_generator_is_optional_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(load_default_rag_answer_generator())

    def test_local_document_retriever_matches_exact_official_issue_without_embeddings(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = Path(directory) / "documents"
            documents.mkdir()
            (documents / "issue-19.md").write_text(
                "---\n"
                "source_type: gitlink_issue\n"
                "trust_level: official\n"
                "source_url: https://www.gitlink.org.cn/metax-maca/op_optimization/issues/19\n"
                "---\n"
                "# 请问能否公开下载比赛镜像？\n\n"
                "可以下载，详见沐曦开发者社区：https://developer.metax-tech.com/\n\n"
                "pytorch镜像如下：\n"
                "https://developer.metax-tech.com/softnova/docker?"
                "chip_name=%E6%9B%A6%E4%BA%91C500%E7%B3%BB%E5%88%97&package_kind=AI&"
                "dimension=docker&deliver_type=%E5%88%86%E5%B1%82%E5%8C%85&ai_frame=pytorch\n\n"
                "相关MACA的文档也比较全，预祝比赛顺利！\n",
                encoding="utf-8",
            )
            retriever = LocalDocumentRagRetriever(load_document_chunks(documents))

            result = retriever.retrieve("请问能否公开下载比赛镜像？")

        assert result is not None
        expected_reply = (
            "可以下载，详见沐曦开发者社区：https://developer.metax-tech.com/\n\n"
            "pytorch镜像如下：\n"
            "https://developer.metax-tech.com/softnova/docker?"
            "chip_name=%E6%9B%A6%E4%BA%91C500%E7%B3%BB%E5%88%97&package_kind=AI&"
            "dimension=docker&deliver_type=%E5%88%86%E5%B1%82%E5%8C%85&ai_frame=pytorch\n\n"
            "相关MACA的文档也比较全，预祝比赛顺利！"
        )
        self.assertTrue(result.is_strong)
        self.assertGreaterEqual(result.confidence, 0.82)
        self.assertEqual(result.reply, expected_reply)
        self.assertIn("issues/19", result.source)

    def test_local_document_retriever_does_not_promote_community_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = Path(directory) / "documents"
            documents.mkdir()
            (documents / "community.md").write_text(
                "---\n"
                "source_type: gitlink_issue\n"
                "trust_level: community\n"
                "source_url: https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops/issues/15\n"
                "---\n"
                "# cmake 构建失败怎么办？\n\n可以尝试重新安装 cmake。\n",
                encoding="utf-8",
            )
            retriever = LocalDocumentRagRetriever(load_document_chunks(documents))

            result = retriever.retrieve("cmake 构建失败怎么办？")

        assert result is not None
        self.assertFalse(result.is_strong)
        self.assertEqual(result.trust_level, "community")

    def test_local_document_retriever_ignores_unrelated_question(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = Path(directory) / "documents"
            documents.mkdir()
            (documents / "issue.md").write_text(
                "---\n"
                "source_type: gitlink_issue\n"
                "trust_level: official\n"
                "source_url: https://www.gitlink.org.cn/example/repo/issues/1\n"
                "---\n"
                "# 比赛镜像怎么下载？\n\n请前往开发者社区下载。\n",
                encoding="utf-8",
            )
            retriever = LocalDocumentRagRetriever(load_document_chunks(documents))

            result = retriever.retrieve("今天上海天气怎么样？")

        self.assertIsNone(result)

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
