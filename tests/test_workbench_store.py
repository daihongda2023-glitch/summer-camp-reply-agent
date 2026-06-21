import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_models import ReplyCandidate, ReplyLogEntry
from summer_camp_agent.workbench_store import ReplyCandidateStore, ReplyLogStore


class WorkbenchStoreTest(unittest.TestCase):
    def test_saves_reply_candidate_as_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reply_candidates.jsonl"
            store = ReplyCandidateStore(path)
            candidate = ReplyCandidate(
                candidate_id="cand-1",
                group_name="夏令营咨询群",
                original_question="营服是什么颜色？",
                agent_reply="当前资料还没有明确说明。",
                edited_reply="营服颜色以后续通知为准。",
                source="人工修改",
                confidence=0.0,
                candidate_type="faq",
                status="pending",
                created_at="2026-06-21T10:00:00+08:00",
            )

            store.append(candidate)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows[0]["candidate_id"], "cand-1")
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["edited_reply"], "营服颜色以后续通知为准。")

    def test_saves_reply_log_as_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reply_logs.jsonl"
            store = ReplyLogStore(path)
            entry = ReplyLogEntry(
                log_id="log-1",
                group_name="夏令营咨询群",
                trigger_message_hash="sha256:message",
                trigger_reasons=["keyword"],
                mode="draft",
                action="send",
                reply="同学你好，报名入口为...",
                source="FAQ / 招募文章",
                confidence=0.96,
                operator_action="sent",
                created_at="2026-06-21T10:00:00+08:00",
            )

            store.append(entry)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows[0]["log_id"], "log-1")
        self.assertEqual(rows[0]["trigger_reasons"], ["keyword"])
        self.assertEqual(rows[0]["operator_action"], "sent")


if __name__ == "__main__":
    unittest.main()
