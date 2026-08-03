import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.knowledge import KnowledgeBase, KnowledgeValidationError


class KnowledgeBaseTest(unittest.TestCase):
    def write_items(self, items):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "faq.json"
        path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(directory.cleanup)
        return path

    def test_loads_valid_faq_items(self):
        path = self.write_items(
            [
                {
                    "id": "faq.registration.link",
                    "stage": "报名申请期",
                    "intent": "registration.link",
                    "question": "报名入口在哪里？",
                    "question_aliases": ["报名链接", "怎么报名"],
                    "answer": "当前资料中的报名入口为：https://v.wjx.cn/vm/r9BqUzR.aspx#",
                    "expired_answer": "报名已经截止。",
                    "source": "招募文章",
                    "source_date": "2026-06",
                    "last_updated": "2026-06-20",
                    "valid_until": "2026-07-15",
                    "auto_reply": True,
                    "needs_human_fallback": False,
                    "human_fallback_reason": "",
                    "owner": "运营",
                }
            ]
        )

        kb = KnowledgeBase.from_json(path)

        self.assertEqual(len(kb.items), 1)
        self.assertEqual(kb.items[0].intent, "registration.link")
        self.assertEqual(kb.items[0].expired_answer, "报名已经截止。")

    def test_auto_reply_requires_source_metadata(self):
        path = self.write_items(
            [
                {
                    "id": "faq.registration.link",
                    "stage": "报名申请期",
                    "intent": "registration.link",
                    "question": "报名入口在哪里？",
                    "question_aliases": [],
                    "answer": "当前资料中的报名入口为：https://v.wjx.cn/vm/r9BqUzR.aspx#",
                    "source": "",
                    "source_date": "2026-06",
                    "last_updated": "2026-06-20",
                    "valid_until": "2026-07-15",
                    "auto_reply": True,
                    "needs_human_fallback": False,
                    "human_fallback_reason": "",
                    "owner": "运营",
                }
            ]
        )

        with self.assertRaisesRegex(KnowledgeValidationError, "source"):
            KnowledgeBase.from_json(path)

    def test_human_fallback_items_require_reason(self):
        path = self.write_items(
            [
                {
                    "id": "faq.selection.result",
                    "stage": "面试选拔期",
                    "intent": "selection.result",
                    "question": "我被录取了吗？",
                    "question_aliases": ["录取结果"],
                    "answer": "",
                    "source": "运营规则",
                    "source_date": "2026-06-20",
                    "last_updated": "2026-06-20",
                    "valid_until": "",
                    "auto_reply": False,
                    "needs_human_fallback": True,
                    "human_fallback_reason": "",
                    "owner": "运营",
                }
            ]
        )

        with self.assertRaisesRegex(KnowledgeValidationError, "human_fallback_reason"):
            KnowledgeBase.from_json(path)


if __name__ == "__main__":
    unittest.main()
