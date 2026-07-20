import unittest
from pathlib import Path

from summer_camp_agent.rag_documents import RagDocumentError, load_document_chunks, split_text_into_chunks


class RagDocumentsTest(unittest.TestCase):
    def test_loads_markdown_and_splits_by_heading(self):
        with self._temp_documents() as root:
            source = root / "handbook.md"
            source.write_text(
                "# 线下手册\n\n"
                "## 住宿安排\n\n"
                "活动期间住宿由主办方统一安排。\n\n"
                "## 交通安排\n\n"
                "往返交通费用由营员自理。",
                encoding="utf-8",
            )

            chunks = load_document_chunks(root, target_chars=30, overlap_chars=5)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].source_title, "线下手册")
        self.assertTrue(any("住宿安排" in chunk.heading for chunk in chunks))
        self.assertTrue(any("往返交通费用" in chunk.text for chunk in chunks))
        self.assertTrue(all(chunk.chunk_id.startswith("sha256:") for chunk in chunks))

    def test_loads_plain_text_with_file_stem_as_title(self):
        with self._temp_documents() as root:
            source = root / "notice.txt"
            source.write_text("报名截止到 2026 年 7 月 15 日。", encoding="utf-8")

            chunks = load_document_chunks(root)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].source_title, "notice")
        self.assertIn("报名截止", chunks[0].text)

    def test_loads_front_matter_as_metadata_without_embedding_it(self):
        with self._temp_documents() as root:
            source = root / "issue-5.md"
            source.write_text(
                "---\n"
                "source_type: gitlink_issue\n"
                "trust_level: community\n"
                "source_url: https://www.gitlink.org.cn/example/repo/issues/5\n"
                "issue_index: \"5\"\n"
                "---\n"
                "# 构建问题\n\n"
                "重新安装 cmake 后构建通过。\n",
                encoding="utf-8",
            )

            chunks = load_document_chunks(root)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["trust_level"], "community")
        self.assertEqual(chunks[0].metadata["issue_index"], "5")
        self.assertNotIn("trust_level", chunks[0].text)
        self.assertNotIn("source_url", chunks[0].text)
        self.assertIn("重新安装 cmake", chunks[0].text)

    def test_rejects_unknown_gitlink_trust_level(self):
        with self._temp_documents() as root:
            (root / "invalid.md").write_text(
                "---\n"
                "source_type: gitlink_issue\n"
                "trust_level: guessed\n"
                "source_url: https://www.gitlink.org.cn/example/repo/issues/1\n"
                "---\n"
                "# 问题\n\n答复。\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RagDocumentError, "trust_level"):
                load_document_chunks(root)

    def test_rejects_non_gitlink_source_url(self):
        with self._temp_documents() as root:
            (root / "invalid-url.md").write_text(
                "---\n"
                "source_type: gitlink_issue\n"
                "trust_level: official\n"
                "source_url: https://example.com/issues/1\n"
                "---\n"
                "# 问题\n\n答复。\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RagDocumentError, "source_url"):
                load_document_chunks(root)

    def test_default_loader_skips_chat_logs_and_generated_index(self):
        with self._temp_documents() as root:
            (root / "guide.md").write_text("# 指南\n\n正式资料。", encoding="utf-8")
            chat_dir = root / "imports" / "chat_logs"
            chat_dir.mkdir(parents=True)
            (chat_dir / "weflow.jsonl").write_text('{"content":"聊天记录"}\n', encoding="utf-8")
            index_dir = root / "data" / "rag" / "index"
            index_dir.mkdir(parents=True)
            (index_dir / "chunks.jsonl").write_text('{"text":"派生索引"}\n', encoding="utf-8")

            chunks = load_document_chunks(root)

        self.assertEqual(len(chunks), 1)
        self.assertIn("正式资料", chunks[0].text)

    def test_split_text_keeps_overlap_when_text_is_long(self):
        chunks = split_text_into_chunks("一二三四五六七八九十", target_chars=4, overlap_chars=2)

        self.assertEqual(chunks, ["一二三四", "三四五六", "五六七八", "七八九十"])

    @staticmethod
    def _temp_documents():
        import tempfile

        class TempDocuments:
            def __enter__(self):
                self.directory = tempfile.TemporaryDirectory()
                return Path(self.directory.name)

            def __exit__(self, exc_type, exc, tb):
                self.directory.cleanup()

        return TempDocuments()


if __name__ == "__main__":
    unittest.main()
