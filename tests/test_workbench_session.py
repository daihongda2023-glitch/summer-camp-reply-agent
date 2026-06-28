import tempfile
import unittest
import json
from pathlib import Path

from summer_camp_agent.workbench_models import ChatEvent, GroupConfig
from summer_camp_agent.workbench_session import WorkbenchSession


class WorkbenchSessionTest(unittest.TestCase):
    def test_process_event_creates_draft_for_triggered_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-1",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )

            item = session.process_event(event)

        self.assertTrue(item.trigger.should_process)
        self.assertEqual(item.reply_decision.mode, "draft")
        self.assertIn("报名入口", item.review_card.reply)

    def test_untriggered_event_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-2",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "收到，谢谢老师",
                "text",
                "manual",
            )

            item = session.process_event(event)

        self.assertFalse(item.trigger.should_process)
        self.assertEqual(item.reply_decision.mode, "ignored")

    def test_send_edited_reply_saves_candidate_and_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-1",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )
            item = session.process_event(event)

            session.confirm_reply(item, edited_reply="同学你好，报名入口请看官方链接。")

            self.assertIn("官方链接", (root / "candidates.jsonl").read_text(encoding="utf-8"))
            self.assertIn("edited_and_sent", (root / "logs.jsonl").read_text(encoding="utf-8"))

    def test_save_candidate_does_not_write_send_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["营服"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-2",
                "sha256:group",
                "夏令营咨询群",
                "成员002",
                "student",
                "2026-06-21 10:05:00",
                "营服是什么颜色？",
                "text",
                "manual",
            )
            item = session.process_event(event)

            session.save_candidate(item, edited_reply="营服颜色以后续官方通知为准。")

            self.assertIn("营服颜色", (root / "candidates.jsonl").read_text(encoding="utf-8"))
            self.assertFalse((root / "logs.jsonl").exists())

    def test_record_operator_action_logs_paste_without_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-paste",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )
            item = session.process_event(event)

            session.record_operator_action(item, item.review_card.reply, operator_action="pasted_to_wechat", action="paste")

            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("pasted_to_wechat", log_text)
            self.assertNotIn("operator_confirmed_sent", log_text)

    def test_confirm_operator_sent_saves_edited_candidate_and_confirmed_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-confirm",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )
            item = session.process_event(event)

            session.confirm_operator_sent(item, "同学你好，报名入口请看官方链接。")

            self.assertIn("官方链接", (root / "candidates.jsonl").read_text(encoding="utf-8"))
            self.assertIn("edited_and_confirmed_sent", (root / "logs.jsonl").read_text(encoding="utf-8"))

    def test_records_work_trace_for_processing_and_confirmed_send(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace_path = root / "work_trace.jsonl"
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                trace_path=trace_path,
            )
            event = ChatEvent(
                "evt-trace",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )

            item = session.process_event(event)
            session.confirm_operator_sent(item, item.review_card.reply)

            rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([row["event_id"] for row in rows], ["evt-trace", "evt-trace", "evt-trace"])
        self.assertEqual([row["phase"] for row in rows], ["observe", "think", "act"])
        self.assertEqual(rows[-1]["action"], "confirm_sent")
        self.assertEqual(rows[-1]["outcome"], "ok")


if __name__ == "__main__":
    unittest.main()
