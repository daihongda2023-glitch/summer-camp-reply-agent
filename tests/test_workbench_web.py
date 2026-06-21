import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_web import WorkbenchWebState


class WorkbenchWebTest(unittest.TestCase):
    def test_demo_items_cover_visible_mvp_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")

            payload = state.load_demo_items()

        statuses = {item["status"] for item in payload["items"]}
        self.assertIn("待审核", statuses)
        self.assertIn("转人工", statuses)
        self.assertIn("待补充", statuses)
        self.assertIn("未触发", statuses)

    def test_ask_and_send_reply_records_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            item = state.ask("报名入口在哪里？")["item"]

            result = state.send_reply(item["event_id"], item["reply"])

            self.assertEqual(result["status"], "ok")
            self.assertIn("报名入口", (root / "logs.jsonl").read_text(encoding="utf-8"))

    def test_import_jsonl_text_processes_uploaded_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            text = json.dumps(
                {
                    "group_name": "夏令营咨询群",
                    "group_id_hash": "sha256:group",
                    "message_time": "2026-06-21 10:00:00",
                    "sender_alias": "成员001",
                    "content": "报名入口在哪里？",
                    "platform_message_id_hash": "sha256:msg",
                    "source": "browser_upload",
                },
                ensure_ascii=False,
            )

            payload = state.import_jsonl_text(text)

        self.assertEqual(payload["items"][0]["event_id"], "sha256:msg")
        self.assertEqual(payload["items"][0]["source"], "browser_upload")


if __name__ == "__main__":
    unittest.main()
