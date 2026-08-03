import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.rag_embeddings import StaticEmbeddingProvider
from summer_camp_agent.rag_index import (
    RagIndexError,
    build_rag_index,
    cosine_similarity,
    load_rag_index,
)


class RagIndexTest(unittest.TestCase):
    def test_build_index_writes_manifest_and_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            index = root / "index"
            documents.mkdir()
            (documents / "notice.md").write_text("# 通知\n\n报名截止到 2026 年 7 月 15 日。", encoding="utf-8")
            provider = StaticEmbeddingProvider(default_embedding=[1.0, 0.0], model="static-model")

            summary = build_rag_index(documents, index, provider)
            rag_index = load_rag_index(index, expected_model="static-model")

        self.assertEqual(summary.chunk_count, 1)
        self.assertEqual(len(rag_index.chunks), 1)
        self.assertEqual(rag_index.manifest["model"], "static-model")
        self.assertEqual(rag_index.chunks[0].embedding, [1.0, 0.0])
        self.assertIn("报名截止", rag_index.chunks[0].text)

    def test_load_index_rejects_model_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            index = root / "index"
            documents.mkdir()
            (documents / "notice.txt").write_text("报名截止到 2026 年 7 月 15 日。", encoding="utf-8")
            provider = StaticEmbeddingProvider(default_embedding=[1.0, 0.0], model="static-model")
            build_rag_index(documents, index, provider)

            with self.assertRaisesRegex(RagIndexError, "索引模型不一致"):
                load_rag_index(index, expected_model="other-model")

    def test_cosine_similarity_scores_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)
        self.assertAlmostEqual(cosine_similarity([0.0, 0.0], [1.0, 0.0]), 0.0)


if __name__ == "__main__":
    unittest.main()
