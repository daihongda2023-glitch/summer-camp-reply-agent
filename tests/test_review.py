import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.engine import AnswerEngine, AnswerResult
from summer_camp_agent.knowledge import KnowledgeBase
from summer_camp_agent.review import OperatorReview, save_pending_question


def make_review():
    engine = AnswerEngine(KnowledgeBase.from_default())
    return OperatorReview(engine)


class OperatorReviewTest(unittest.TestCase):
    def test_review_card_preserves_rag_ai_generation_metadata(self):
        class StaticEngine:
            def answer(self, question):
                return AnswerResult(
                    action="auto_reply",
                    reply="AI 整理后的回复",
                    intent="rag.document",
                    source="官方 RAG",
                    confidence=0.96,
                    generation_mode="rag_ai",
                    generation_model="fake-model",
                    generation_error="",
                )

        card = OperatorReview(StaticEngine()).create_card("比赛镜像能下载吗？")

        self.assertEqual(card.generation_mode, "rag_ai")
        self.assertEqual(card.generation_model, "fake-model")
        self.assertEqual(card.generation_error, "")

    def test_auto_reply_question_recommends_send(self):
        card = make_review().create_card("报名入口在哪里？")

        self.assertEqual(card.recommendation, "send")
        self.assertEqual(card.action, "auto_reply")
        self.assertIn("send", card.available_actions)
        self.assertIn("edit", card.available_actions)
        self.assertIn("官方咨询群海报", card.source)
        self.assertIn("https://developer.metax-tech.com/activities/18", card.reply)
        self.assertNotIn("v.wjx.cn", card.reply)

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
