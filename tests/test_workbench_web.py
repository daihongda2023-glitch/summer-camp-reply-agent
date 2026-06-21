import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_web import WORKBENCH_HTML, WorkbenchWebState, create_handler


class WorkbenchWebTest(unittest.TestCase):
    def test_html_exposes_wechat_assisted_controls(self):
        self.assertIn('id="wechatGroupName"', WORKBENCH_HTML)
        self.assertIn("saveWechatConfig()", WORKBENCH_HTML)
        self.assertIn("pasteToWechat()", WORKBENCH_HTML)
        self.assertIn("confirmSent()", WORKBENCH_HTML)
        self.assertIn("setInterval", WORKBENCH_HTML)
        self.assertIn("/api/wechat/poll", WORKBENCH_HTML)
        self.assertIn("grid-template-rows: minmax(92px, 1fr) auto;", WORKBENCH_HTML)
        self.assertIn("flex-wrap: wrap;", WORKBENCH_HTML)
        self.assertIn("justify-content: flex-end;", WORKBENCH_HTML)

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


class FakeListener:
    def __init__(self, events):
        self.events = events
        self.poll_count = 0

    def poll_once(self):
        from summer_camp_agent.wechat_live_listener import ListenerPollResult

        self.poll_count += 1
        return ListenerPollResult("ok", "ok", self.events)


class FakePasteAdapter:
    def __init__(self):
        self.pasted = []

    def paste_to_foreground(self, text):
        from summer_camp_agent.wechat_assisted_paste import PasteResult

        self.pasted.append(text)
        return PasteResult("pasted", "已填入当前前台窗口，请在微信中确认后手动发送。", "微信")


class WorkbenchWebWechatBridgeTest(unittest.TestCase):
    def test_poll_wechat_once_adds_listener_events_to_items(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-live",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-06-21 10:00:00",
            "报名入口在哪里？",
            "text",
            "weflow_live",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.wechat_listener = FakeListener([event])

            payload = state.poll_wechat_once()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["items"][0]["event_id"], "evt-live")

    def test_paste_reply_logs_paste_but_not_confirmed_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.paste_adapter = FakePasteAdapter()
            item = state.ask("报名入口在哪里？")["item"]

            result = state.paste_reply(item["event_id"], item["reply"])

            self.assertEqual(result["paste_action"], "pasted")
            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("pasted_to_wechat", log_text)
            self.assertNotIn("operator_confirmed_sent", log_text)

    def test_confirm_sent_records_operator_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            item = state.ask("报名入口在哪里？")["item"]

            result = state.confirm_sent(item["event_id"], item["reply"])

            self.assertEqual(result["status"], "ok")
            self.assertIn("operator_confirmed_sent", (root / "logs.jsonl").read_text(encoding="utf-8"))

    def test_wechat_paste_route_returns_structured_result(self):
        from http.server import ThreadingHTTPServer
        import threading
        import urllib.request

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.paste_adapter = FakePasteAdapter()
            item = state.ask("报名入口在哪里？")["item"]
            server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/wechat/paste",
                    data=json.dumps({"event_id": item["event_id"], "reply": item["reply"]}, ensure_ascii=False).encode(
                        "utf-8"
                    ),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                payload = json.loads(urllib.request.urlopen(request, timeout=5).read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(payload["paste_action"], "pasted")
        self.assertIn("手动发送", payload["message"])


if __name__ == "__main__":
    unittest.main()
