import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_models import ChatEvent, ReplyCandidate, ReplyLogEntry
from summer_camp_agent.workbench_store import (
    ReplyCandidateStore,
    ReplyLogStore,
    WorkbenchInboxStore,
)


def chat_event(event_id, content):
    return ChatEvent(
        event_id=event_id,
        group_id_hash="sha256:group",
        group_name="测试群",
        sender_alias="成员001",
        sender_role="student",
        message_time="2026-07-23 12:00:00",
        content=content,
        raw_type="text",
        source="weflow_live",
    )


class WorkbenchStoreTest(unittest.TestCase):
    def test_inbox_upserts_deduplicates_caps_and_removes_chat_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workbench_inbox.jsonl"
            store = WorkbenchInboxStore(path, max_items=2)
            store.upsert(chat_event("evt-1", "问题一？"))
            store.upsert(chat_event("evt-1", "问题一更新？"))
            store.upsert(chat_event("evt-2", "问题二？"))
            store.upsert(chat_event("evt-3", "问题三？"))

            loaded = store.load()
            store.remove("evt-2")
            remaining = store.load()

        self.assertEqual(
            [(item.event_id, item.content) for item in loaded],
            [("evt-2", "问题二？"), ("evt-3", "问题三？")],
        )
        self.assertEqual([item.event_id for item in remaining], ["evt-3"])

    def test_inbox_ignores_corrupt_rows_and_preserves_valid_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workbench_inbox.jsonl"
            valid = chat_event("evt-valid", "有效问题？")
            path.write_text(
                "{not-json}\n"
                + json.dumps(valid.__dict__, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )

            loaded = WorkbenchInboxStore(path).load()

        self.assertEqual([item.event_id for item in loaded], ["evt-valid"])

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
                generation_mode="rag_ai",
                generation_model="gpt-test",
                generation_error="",
            )

            store.append(entry)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows[0]["log_id"], "log-1")
        self.assertEqual(rows[0]["trigger_reasons"], ["keyword"])
        self.assertEqual(rows[0]["operator_action"], "sent")
        self.assertEqual(rows[0]["generation_mode"], "rag_ai")
        self.assertEqual(rows[0]["generation_model"], "gpt-test")
        self.assertEqual(rows[0]["generation_error"], "")


if __name__ == "__main__":
    unittest.main()
