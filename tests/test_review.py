import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.engine import AnswerEngine
from summer_camp_agent.knowledge import KnowledgeBase
from summer_camp_agent.review import OperatorReview, save_pending_question


def make_review():
    engine = AnswerEngine(KnowledgeBase.from_default())
    return OperatorReview(engine)


class OperatorReviewTest(unittest.TestCase):
    def test_auto_reply_question_recommends_send(self):
        card = make_review().create_card("报名入口在哪里？")

        self.assertEqual(card.recommendation, "send")
        self.assertEqual(card.action, "auto_reply")
        self.assertIn("send", card.available_actions)
        self.assertIn("edit", card.available_actions)
        self.assertIn("招募文章", card.source)
        self.assertIn("https://v.wjx.cn/vm/r9BqUzR.aspx#", card.reply)

    def test_unknown_question_recommends_mark_pending_without_record_claim(self):
        card = make_review().create_card("营服是什么颜色？")

        self.assertEqual(card.recommendation, "mark_pending")
        self.assertEqual(card.action, "needs_info")
        self.assertIn("mark_pending", card.available_actions)
        self.assertNotIn("已记录", card.reply)

    def test_human_fallback_question_recommends_escalate(self):
        card = make_review().create_card("老师，我被录取了吗？")

        self.assertEqual(card.recommendation, "escalate")
        self.assertEqual(card.action, "human_fallback")
        self.assertEqual(card.reason, "personal_status")
        self.assertIn("escalate", card.available_actions)

    def test_can_save_unknown_question_to_pending_jsonl(self):
        card = make_review().create_card("营服是什么颜色？")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending.jsonl"

            save_pending_question(card, path)

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["original_question"], "营服是什么颜色？")
            self.assertEqual(payload["status"], "待确认")
            self.assertEqual(payload["recommended_owner"], "运营")


if __name__ == "__main__":
    unittest.main()
