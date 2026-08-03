import tempfile
import unittest
from pathlib import Path

from scripts.verify_semantic_reply_scenarios import (
    QUESTIONS,
    SUPPORT_REPLY,
    run_verification,
)


class SemanticReplyScenarioTest(unittest.TestCase):
    def test_three_reported_questions_auto_send_when_faq_or_rag_hits(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_verification(Path(directory))

        rows = {
            row["question"]: row
            for row in result["results"]
        }
        scoring = rows[QUESTIONS[0]]
        support = rows[QUESTIONS[1]]
        location = rows[QUESTIONS[2]]

        self.assertEqual(result["status"], "ok")

        self.assertEqual(scoring["mode"], "auto_send")
        self.assertTrue(scoring["replied"])
        self.assertEqual(scoring["generation_mode"], "rag_insufficient")
        self.assertEqual(scoring["semantic_intent"], "evaluation.scoring")
        self.assertEqual(scoring["semantic_confidence"], 0.94)
        self.assertEqual(scoring["faq_confidence"], 0.0)
        self.assertGreater(scoring["rag_confidence"], 0.20)
        self.assertLess(scoring["rag_confidence"], 0.30)
        self.assertEqual(scoring["reason"], "not_grounded")
        self.assertIn("没有说明", scoring["reply"])
        self.assertIn("XPU-OJ 平台的正式评测结果为准", scoring["reply"])

        self.assertEqual(support["mode"], "auto_send")
        self.assertTrue(support["replied"])
        self.assertEqual(support["generation_mode"], "rag_ai")
        self.assertEqual(support["semantic_intent"], "support.contact")
        self.assertEqual(support["semantic_confidence"], 0.95)
        self.assertEqual(support["faq_confidence"], 0.50)
        self.assertGreater(support["rag_confidence"], 0.06)
        self.assertLess(support["rag_confidence"], 0.08)
        self.assertEqual(support["reply"], SUPPORT_REPLY)

        self.assertEqual(location["mode"], "auto_send")
        self.assertTrue(location["replied"])
        self.assertEqual(location["generation_mode"], "faq")
        self.assertEqual(location["semantic_intent"], "offline.location")
        self.assertEqual(location["semantic_confidence"], 0.98)
        self.assertEqual(location["faq_confidence"], 0.90)
        self.assertEqual(location["rag_confidence"], 0.0)
        self.assertEqual(
            location["reply"],
            "线下夏令营时间为 2026 年 8 月 3 日至 8 月 7 日，"
            "地点为上海交通大学、沐曦股份。"
            "具体报到地点和每日场地以最终入营通知为准。",
        )

        self.assertEqual(
            result["sent_replies"],
            [scoring["reply"], support["reply"], location["reply"]],
        )
        self.assertEqual(result["pending_after_restart"], [])


if __name__ == "__main__":
    unittest.main()
