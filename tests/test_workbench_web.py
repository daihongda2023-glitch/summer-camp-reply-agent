import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_web import WORKBENCH_HTML, WorkbenchWebState, create_handler
from summer_camp_agent.wechat_bridge_config import DEFAULT_GROUP_NAME
from summer_camp_agent.weflow_import import WeFlowSession


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
        self.assertIn('id="wechatDebugConfig"', WORKBENCH_HTML)
        self.assertIn('id="wechatSessionId"', WORKBENCH_HTML)
        self.assertIn("let currentWechatConfig", WORKBENCH_HTML)
        self.assertIn("loadWechatConfig()", WORKBENCH_HTML)
        self.assertIn("applyWechatConfig", WORKBENCH_HTML)
        self.assertIn("show_debug_config", WORKBENCH_HTML)
        self.assertNotIn("session_id: ''", WORKBENCH_HTML)

    def test_default_wechat_config_uses_target_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=root / "wechat_bridge_config.json",
            )

            payload = state.get_wechat_config()

        self.assertEqual(payload["config"]["group_name"], DEFAULT_GROUP_NAME)

    def test_html_stops_wechat_polling_after_listener_error(self):
        self.assertIn("if (data.status === 'error')", WORKBENCH_HTML)
        self.assertIn("clearWechatPolling();", WORKBENCH_HTML)

    def test_layout_keeps_reply_bar_out_of_left_sidebar(self):
        self.assertIn(".left {\n      grid-column: 1;\n      grid-row: 1 / 4;", WORKBENCH_HTML)
        self.assertIn("overflow: auto;", WORKBENCH_HTML)
        self.assertIn(".reply {\n      grid-column: 2 / 4;", WORKBENCH_HTML)
        self.assertIn(".statusbar {\n      grid-column: 2 / 4;", WORKBENCH_HTML)

    def test_html_prefers_weflow_group_import_over_jsonl_upload(self):
        self.assertIn("importWeFlowGroup()", WORKBENCH_HTML)
        self.assertIn("/api/import-weflow", WORKBENCH_HTML)
        self.assertIn("从 WeFlow 导入", WORKBENCH_HTML)
        self.assertNotIn("导入 JSONL", WORKBENCH_HTML)
        self.assertNotIn('id="jsonlFile"', WORKBENCH_HTML)

    def test_html_maps_decision_panel_machine_values_to_chinese(self):
        self.assertIn("formatDecisionValue", WORKBENCH_HTML)
        self.assertIn("triggerReasonLabels", WORKBENCH_HTML)
        self.assertIn("recommendationLabels", WORKBENCH_HTML)
        self.assertIn("engineActionLabels", WORKBENCH_HTML)
        self.assertIn("intentLabels", WORKBENCH_HTML)
        self.assertIn("关键词命中", WORKBENCH_HTML)
        self.assertIn("问号问题", WORKBENCH_HTML)
        self.assertIn("建议发送", WORKBENCH_HTML)
        self.assertIn("自动回复", WORKBENCH_HTML)
        self.assertIn("报名入口", WORKBENCH_HTML)

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

    def test_import_weflow_group_processes_messages_from_named_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            client = FakeWeFlowImportClient()

            payload = state.import_weflow_group("测试群", client=client, token="fake-token")

        self.assertEqual(client.search_calls, ["测试群"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["items"][0]["group_name"], "测试群")
        self.assertEqual(payload["items"][0]["question"], "报名入口在哪里？")
        self.assertEqual(payload["items"][0]["source"], "weflow_api")


class FakeListener:
    def __init__(self, events):
        self.events = events
        self.poll_count = 0

    def poll_once(self):
        from summer_camp_agent.wechat_live_listener import ListenerPollResult

        self.poll_count += 1
        return ListenerPollResult("ok", "ok", self.events)


class FakeWeFlowImportClient:
    def __init__(self):
        self.search_calls = []

    def search_sessions(self, keyword):
        self.search_calls.append(keyword)
        return [WeFlowSession(id="room@chatroom", name="测试群", type="group")]

    def pull_messages(self, session_id, *, since, end, limit, offset):
        return {
            "meta": {"groupId": session_id},
            "messages": [
                {
                    "sender": "wxid_a",
                    "timestamp": 1781911260,
                    "type": 0,
                    "content": "报名入口在哪里？",
                    "platformMessageId": "msg-1",
                },
                {
                    "sender": "wxid_b",
                    "timestamp": 1781911320,
                    "type": 0,
                    "content": "收到，谢谢老师",
                    "platformMessageId": "msg-2",
                },
            ],
            "sync": {"hasMore": False},
        }


class FakePasteAdapter:
    def __init__(self):
        self.pasted = []

    def paste_to_foreground(self, text):
        from summer_camp_agent.wechat_assisted_paste import PasteResult

        self.pasted.append(text)
        return PasteResult("pasted", "已填入当前前台窗口，请在微信中确认后手动发送。", "微信")


class WorkbenchWebWechatBridgeTest(unittest.TestCase):
    def test_start_listener_uses_saved_wechat_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "wechat_bridge_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "http://127.0.0.1:5031",
                        "token_env": "WEFLOW_API_TOKEN",
                        "group_name": "测试群",
                        "session_id": "",
                        "keywords": ["报名"],
                        "poll_interval_seconds": 5,
                        "enabled": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state = WorkbenchWebState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )

            payload = state.start_wechat_listener()

        self.assertEqual(payload["listener_state"]["group_name"], "测试群")

    def test_get_wechat_config_returns_saved_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "wechat_bridge_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "http://127.0.0.1:5031",
                        "token_env": "WEFLOW_API_TOKEN",
                        "group_name": "test group",
                        "session_id": "room@chatroom",
                        "keywords": ["signup"],
                        "poll_interval_seconds": 7,
                        "enabled": True,
                        "show_debug_config": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state = WorkbenchWebState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )

            payload = state.get_wechat_config()

        self.assertEqual(payload["config"]["session_id"], "room@chatroom")
        self.assertEqual(payload["config"]["keywords"], ["signup"])
        self.assertTrue(payload["config"]["show_debug_config"])

    def test_wechat_config_get_route_returns_current_config(self):
        from http.server import ThreadingHTTPServer
        import threading
        import urllib.request

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "wechat_bridge_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "http://127.0.0.1:5031",
                        "token_env": "WEFLOW_API_TOKEN",
                        "group_name": "test group",
                        "session_id": "room@chatroom",
                        "keywords": ["signup"],
                        "poll_interval_seconds": 7,
                        "enabled": True,
                        "show_debug_config": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state = WorkbenchWebState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                payload = json.loads(
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_address[1]}/api/wechat/config",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(payload["config"]["session_id"], "room@chatroom")
        self.assertTrue(payload["config"]["show_debug_config"])

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
