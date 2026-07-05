import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_api import WorkbenchApiState, create_handler
from summer_camp_agent.wechat_bridge_config import DEFAULT_GROUP_NAME
from summer_camp_agent.weflow_import import WeFlowSession


class WorkbenchApiTest(unittest.TestCase):
    def test_root_route_no_longer_serves_browser_workbench(self):
        from http.server import ThreadingHTTPServer
        import threading
        import urllib.error
        import urllib.request

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/", timeout=5)
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(raised.exception.code, 404)

    def test_default_wechat_config_uses_target_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=root / "wechat_bridge_config.json",
            )

            payload = state.get_wechat_config()

        self.assertEqual(payload["config"]["group_name"], DEFAULT_GROUP_NAME)

    def test_app_settings_api_round_trips_desktop_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                desktop_settings_path=root / "desktop_settings.json",
            )

            payload = state.update_app_settings(
                {
                    "main_view": {
                        "show_target": False,
                        "show_recent_logs": True,
                        "show_history_entry": True,
                        "show_status_detail": True,
                        "show_assist_actions": False,
                    },
                    "advanced_pages": {
                        "messages": True,
                        "candidates": True,
                        "work_trace": False,
                        "rag": True,
                    },
                }
            )
            reloaded = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                desktop_settings_path=root / "desktop_settings.json",
            ).get_app_settings()

        self.assertEqual(payload["settings"]["main_view"]["show_target"], False)
        self.assertEqual(reloaded["settings"]["main_view"]["show_status_detail"], True)
        self.assertEqual(reloaded["settings"]["advanced_pages"]["rag"], True)

    def test_app_settings_api_round_trips_wechat_bridge_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "wechat_bridge_config.json"
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )

            payload = state.update_app_settings(
                {
                    "wechat": {
                        "base_url": "http://127.0.0.1:5031",
                        "token_env": "WEFLOW_API_TOKEN",
                        "group_name": "宝宝守护群",
                        "session_id": "",
                        "keywords": ["报名", "住宿", "GPU"],
                        "poll_interval_seconds": 8,
                        "enabled": True,
                        "show_debug_config": False,
                    }
                }
            )
            reloaded = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            ).get_app_settings()

        self.assertEqual(payload["wechat"]["group_name"], "宝宝守护群")
        self.assertEqual(payload["wechat"]["keywords"], ["报名", "住宿", "GPU"])
        self.assertEqual(payload["wechat"]["poll_interval_seconds"], 8)
        self.assertEqual(reloaded["wechat"]["group_name"], "宝宝守护群")
        self.assertEqual(reloaded["wechat"]["keywords"], ["报名", "住宿", "GPU"])

    def test_app_status_reflects_start_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")

            idle = state.get_app_status()
            started = state.start_app()
            stopped = state.stop_app()

        self.assertEqual(idle["engine"]["status"], "idle")
        self.assertEqual(started["engine"]["status"], "running")
        self.assertEqual(stopped["engine"]["status"], "idle")

    def test_demo_items_cover_visible_mvp_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")

            payload = state.load_demo_items()

        statuses = {item["status"] for item in payload["items"]}
        self.assertIn("待审核", statuses)
        self.assertIn("转人工", statuses)
        self.assertIn("待补充", statuses)
        self.assertIn("未触发", statuses)

    def test_work_trace_api_returns_recorded_processing_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")

            state.load_demo_items()
            payload = state.list_work_trace()

        self.assertGreaterEqual(payload["summary"]["observed"], 1)
        self.assertGreaterEqual(payload["summary"]["thought"], 1)
        self.assertEqual(payload["summary"]["total"], len(payload["trace"]))
        self.assertIn(payload["trace"][0]["phase"], {"observe", "think", "act"})

    def test_ask_and_send_reply_records_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            item = state.ask("报名入口在哪里？")["item"]

            result = state.send_reply(item["event_id"], item["reply"])

            self.assertEqual(result["status"], "ok")
            self.assertIn("报名入口", (root / "logs.jsonl").read_text(encoding="utf-8"))

    def test_import_jsonl_text_processes_uploaded_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
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
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
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
            state = WorkbenchApiState(
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
            state = WorkbenchApiState(
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
            state = WorkbenchApiState(
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
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.wechat_listener = FakeListener([event])

            payload = state.poll_wechat_once()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["items"][0]["event_id"], "evt-live")

    def test_poll_wechat_once_uses_updated_wechat_keywords_for_triggering(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-keyword",
            "sha256:group",
            "测试群",
            "成员002",
            "student",
            "2026-06-21 10:00:00",
            "测试",
            "text",
            "weflow_live",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=root / "wechat_bridge_config.json",
            )
            state.configure_wechat(
                {
                    "base_url": "http://127.0.0.1:5031",
                    "token_env": "WEFLOW_API_TOKEN",
                    "group_name": "测试群",
                    "session_id": "",
                    "keywords": ["测试"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": True,
                }
            )
            state.wechat_listener = FakeListener([event])

            payload = state.poll_wechat_once()

        self.assertNotEqual(payload["items"][0]["status"], "未触发")
        self.assertEqual(payload["items"][0]["matched_keywords"], ["测试"])
        self.assertIn("keyword", payload["items"][0]["trigger_reasons"])

    def test_configure_wechat_refreshes_running_listener_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=root / "wechat_bridge_config.json",
            )

            state.start_wechat_listener()
            state.configure_wechat(
                {
                    "base_url": "http://127.0.0.1:5031",
                    "token_env": "WEFLOW_API_TOKEN",
                    "group_name": "测试群",
                    "session_id": "",
                    "keywords": ["测试"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": True,
                }
            )

        self.assertEqual(state.wechat_listener.config.keywords, ["测试"])
        self.assertEqual(state.wechat_listener.config.group_name, "测试群")

    def test_configure_wechat_reprocesses_existing_untriggered_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=root / "wechat_bridge_config.json",
            )
            initial = state.ask("测试")

            payload = state.configure_wechat(
                {
                    "base_url": "http://127.0.0.1:5031",
                    "token_env": "WEFLOW_API_TOKEN",
                    "group_name": "测试群",
                    "session_id": "",
                    "keywords": ["测试"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": True,
                }
            )

        self.assertEqual(initial["item"]["status"], "未触发")
        self.assertNotEqual(payload["items"][0]["status"], "未触发")
        self.assertEqual(payload["items"][0]["matched_keywords"], ["测试"])

    def test_paste_reply_logs_paste_but_not_confirmed_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
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
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
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
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
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


class FakeVisionObserver:
    def __init__(self):
        from summer_camp_agent.wechat_vision import VisionState

        self.state = VisionState(running=False, window_title="微信群 - 微信")
        self.last_screenshot = b""

    def start(self):
        from summer_camp_agent.wechat_vision import VisionState

        self.state = VisionState(running=True, window_title="微信群 - 微信")
        return self.state

    def stop(self):
        from summer_camp_agent.wechat_vision import VisionState

        self.state = VisionState(running=False, window_title="微信群 - 微信")
        return self.state

    def capture_once(self, screenshot, *, window_title, group_name):
        from summer_camp_agent.wechat_vision import VisionCaptureResult, VisionState
        from summer_camp_agent.workbench_models import ChatEvent

        self.last_screenshot = screenshot
        event = ChatEvent(
            "vision-evt-1",
            "sha256:vision-group",
            group_name,
            "成员001",
            "student",
            "2026-07-02 20:00:00",
            "报名入口在哪里？",
            "text",
            "wechat_pc_vision",
        )
        self.state = VisionState(running=True, window_title=window_title, last_message=event.content)
        return VisionCaptureResult("ok", "已识别 1 条新消息", [event], self.state)


class FakeVisionWindowBackend:
    def __init__(self, status="ok", message="已截取微信窗口。", screenshot=b"fake-bmp", window_title="微信群 - 微信"):
        self.status = status
        self.message = message
        self.screenshot = screenshot
        self.window_title = window_title

    def capture_wechat_window(self):
        from summer_camp_agent.wechat_window import WeChatWindowCapture

        return WeChatWindowCapture(
            self.status,
            self.message,
            screenshot=self.screenshot,
            window_title=self.window_title,
        )


class WorkbenchVisionApiTest(unittest.TestCase):
    def test_vision_capture_processes_events_into_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.vision_observer = FakeVisionObserver()
            state.vision_window_backend = FakeVisionWindowBackend()

            payload = state.capture_vision_once()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["items"][0]["source"], "wechat_pc_vision")
        self.assertEqual(payload["items"][0]["question"], "报名入口在哪里？")
        self.assertEqual(payload["vision"]["last_message"], "报名入口在哪里？")
        self.assertEqual(state.vision_observer.last_screenshot, b"fake-bmp")

    def test_vision_capture_reports_missing_wechat_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.vision_observer = FakeVisionObserver()
            state.vision_window_backend = FakeVisionWindowBackend(
                status="not_found",
                message="未找到可见的微信窗口，请先打开微信 PC。",
                screenshot=b"",
                window_title="",
            )

            payload = state.capture_vision_once()

        self.assertEqual(payload["status"], "not_found")
        self.assertEqual(payload["items"], [])
        self.assertIn("未找到可见的微信窗口", payload["vision"]["last_error"])

    def test_vision_start_and_stop_return_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.vision_observer = FakeVisionObserver()
            state.vision_window_backend = FakeVisionWindowBackend()

            started = state.start_vision()
            stopped = state.stop_vision()

        self.assertTrue(started["vision"]["running"])
        self.assertFalse(stopped["vision"]["running"])


if __name__ == "__main__":
    unittest.main()
