import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_sources import ChatSourceError, JsonlChatSource


class WorkbenchSourcesTest(unittest.TestCase):
    def test_reads_sanitized_jsonl_as_chat_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.jsonl"
            row = {
                "group_name": "夏令营咨询群",
                "group_id_hash": "sha256:group",
                "message_time": "2026-06-21 10:00:00",
                "sender_alias": "成员001",
                "sender_role": "unknown",
                "content": "报名入口在哪里？",
                "platform_message_id_hash": "sha256:msg",
                "raw_type": 0,
                "source": "weflow_api",
            }
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            events = JsonlChatSource(path).load_events()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "sha256:msg")
        self.assertEqual(events[0].content, "报名入口在哪里？")
        self.assertEqual(events[0].source, "weflow_api")

    def test_missing_jsonl_file_has_chinese_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.jsonl"

            with self.assertRaisesRegex(ChatSourceError, "聊天记录文件不存在"):
                JsonlChatSource(path).load_events()

    def test_demo_chat_jsonl_is_loadable(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "workbench_demo_chat.jsonl"

        events = JsonlChatSource(path).load_events()

        self.assertGreaterEqual(len(events), 4)
        self.assertTrue(any("报名入口" in event.content for event in events))
        self.assertTrue(any(event.source == "demo_jsonl" for event in events))


if __name__ == "__main__":
    unittest.main()
