import tempfile
import unittest
from pathlib import Path

from scripts.verify_debug_review_workflow import (
    ORDINARY_MESSAGE,
    QUESTIONS,
    run_verification,
)


class DebugReviewWorkflowTest(unittest.TestCase):
    def test_debug_review_workflow_persists_diagnoses_and_completes_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_verification(Path(directory))

        self.assertEqual(result["pending_before_actions"], 4)
        self.assertEqual(result["auto_sent"], [])
        self.assertEqual(
            result["results"][ORDINARY_MESSAGE]["unmatched_reasons"],
            [
                "missing_question_mark",
                "missing_question_word",
                "missing_keyword",
                "missing_agent_mention",
            ],
        )
        self.assertEqual(
            result["results"][ORDINARY_MESSAGE]["unmatched_reason_labels"],
            ["没有问号", "没有命中常用疑问词", "没有命中关键词", "没有 @ 助手"],
        )
        for question in QUESTIONS:
            with self.subTest(question=question):
                item = result["results"][question]
                self.assertEqual(item["review_status_before"], "pending_review")
                self.assertIn("confidence", item)
                self.assertIn("semantic_confidence", item)
                self.assertIn("faq_confidence", item)
                self.assertIn("rag_confidence", item)
                self.assertTrue(item["reply"])

        self.assertGreaterEqual(
            result["results"]["线下夏令营在哪？"]["faq_confidence"],
            0.90,
        )
        self.assertEqual(
            result["history_statuses"],
            {
                "debug-xpuoj": "review_completed",
                "debug-support": "escalated",
                "debug-location": "sent",
                "debug-ordinary": "review_completed",
            },
        )
        self.assertEqual(result["pending_after_actions"], 0)
        self.assertEqual(result["pending_after_restart"], 0)


if __name__ == "__main__":
    unittest.main()
