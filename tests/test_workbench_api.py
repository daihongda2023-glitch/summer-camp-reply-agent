import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from summer_camp_agent.rag_ai import RagGenerationResult
from summer_camp_agent.workbench_api import WorkbenchApiState, create_handler
from summer_camp_agent.wechat_bridge_config import DEFAULT_GROUP_NAME
from summer_camp_agent.workbench_models import ChatEvent
from summer_camp_agent.workbench_store import WorkbenchInboxStore
from summer_camp_agent.weflow_import import WeFlowSession


class WorkbenchApiTest(unittest.TestCase):
    def test_message_is_persisted_with_unique_key_and_moves_to_sent_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )

            item = state.ask("报名入口在哪里？")["item"]
            pending = state.list_items()["items"]
            state.send_reply(item["message_id"], item["reply"])
            remaining = state.list_items()["items"]
            history = state.list_items(scope="all")["items"]
            database_exists = (root / "workbench_messages.sqlite3").exists()

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["message_id"], pending[0]["event_id"])
        self.assertEqual(pending[0]["review_status"], "pending_review")
        self.assertEqual(remaining, [])
        self.assertEqual(history[0]["review_status"], "sent")
        self.assertTrue(history[0]["completed_at"])
        self.assertTrue(database_exists)

    def test_all_completion_actions_move_message_out_of_pending_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            sent = state.ask("报名入口在哪里？")["item"]
            candidate = state.ask("住宿如何安排？")["item"]
            escalated = state.ask("我为什么没有录取？")["item"]
            completed = state.ask("收到，谢谢老师")["item"]

            state.send_reply(sent["message_id"], sent["reply"])
            state.save_candidate(candidate["message_id"], candidate["reply"])
            state.escalate_message(escalated["message_id"], "需要老师人工确认")
            state.complete_review(completed["message_id"], "无需回复")
            statuses = {
                item["message_id"]: item["review_status"]
                for item in state.list_items(scope="all")["items"]
            }
            remaining = state.list_items()["items"]

        self.assertEqual(remaining, [])
        self.assertEqual(statuses[sent["message_id"]], "sent")
        self.assertEqual(statuses[candidate["message_id"]], "candidate_saved")
        self.assertEqual(statuses[escalated["message_id"]], "escalated")
        self.assertEqual(statuses[completed["message_id"]], "review_completed")

    def test_legacy_jsonl_inbox_migrates_once_and_restart_uses_snapshot(self):
        event = ChatEvent(
            "evt-legacy-migrate",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-07-25 10:00:00",
            "报名入口在哪里？",
            "text",
            "weflow_live",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            WorkbenchInboxStore(root / "workbench_inbox.jsonl").upsert(event)
            first = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            self.assertEqual(
                [item["message_id"] for item in first.list_items()["items"]],
                [event.event_id],
            )

            with patch(
                "summer_camp_agent.workbench_session.WorkbenchSession.process_event",
                side_effect=AssertionError("重启不应重新运行 AI"),
            ):
                restarted = WorkbenchApiState(
                    candidate_path=root / "candidates.jsonl",
                    log_path=root / "logs.jsonl",
                )
                restored = restarted.list_items()["items"]
            legacy_inbox_kept = (root / "workbench_inbox.jsonl").exists()

        self.assertEqual([item["message_id"] for item in restored], [event.event_id])
        self.assertTrue(legacy_inbox_kept)
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
                        "send_mode": "auto_send",
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
        self.assertEqual(payload["wechat"]["send_mode"], "auto_send")
        self.assertEqual(reloaded["wechat"]["group_name"], "宝宝守护群")
        self.assertEqual(reloaded["wechat"]["keywords"], ["报名", "住宿", "GPU"])
        self.assertEqual(reloaded["wechat"]["send_mode"], "auto_send")

    def test_app_status_reflects_start_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=root / "wechat_bridge_config.json",
            )

            idle = state.get_app_status()
            started = state.start_app()
            stopped = state.stop_app()

        self.assertEqual(idle["engine"]["status"], "idle")
        self.assertEqual(started["engine"]["status"], "running")
        self.assertEqual(stopped["engine"]["status"], "idle")
        self.assertEqual(idle["engine"]["send_mode"], "manual_confirm")

    def test_demo_items_cover_visible_mvp_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")

            payload = state.load_demo_items()

        self.assertEqual({item["review_status"] for item in payload["items"]}, {"pending_review"})
        self.assertTrue(all(item["status"] == "待审核" for item in payload["items"]))
        self.assertTrue(all(item["mode"] == "draft" for item in payload["items"]))

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
            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("trigger_message_hash", log_text)
            self.assertIn(item["reply"], log_text)
            self.assertNotIn("报名入口在哪里？", log_text)

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


class ReplyAwareFakeListener(FakeListener):
    def __init__(self, events):
        super().__init__(events)
        self.replied_event_ids = []
        self.sent_replies = []

    def mark_replied(self, event_id, reply=""):
        self.replied_event_ids.append(event_id)
        self.sent_replies.append(reply)

    def is_replied(self, event_id):
        return event_id in self.replied_event_ids


class IncludeSeenRecordingListener:
    def __init__(self):
        self.include_seen_values = []

    def poll_once(self, *, include_seen=False):
        from summer_camp_agent.wechat_live_listener import ListenerPollResult

        self.include_seen_values.append(include_seen)
        return ListenerPollResult("ok", "ok", [])


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
        self.sent = []

    def paste_to_foreground(self, text, target_group_name=""):
        from summer_camp_agent.wechat_assisted_paste import PasteResult

        self.pasted.append(text)
        return PasteResult(
            "filled_verified",
            "已填入并校验，请在微信中检查后手动发送。",
            "测试群 - 微信",
            target_found=True,
            input_focused=True,
            filled=True,
            verified=True,
            target_status="matched",
            input_status="focused",
            verification_status="matched",
        )

    def paste_to_wechat_foreground(self, text, target_group_name=""):
        return self.paste_to_foreground(text, target_group_name)

    def send_to_wechat_foreground(self, text, target_group_name=""):
        from summer_camp_agent.wechat_assisted_paste import PasteResult

        self.sent.append(text)
        return PasteResult(
            "sent_verified",
            "已自动发布到微信。",
            "测试群 - 微信",
            target_found=True,
            input_focused=True,
            filled=True,
            verified=True,
            target_status="matched",
            input_status="focused",
            verification_status="matched",
        )


class FakeRagAnswerGenerator:
    model = "fake-model"

    def generate(self, question, rag_result):
        return RagGenerationResult(
            "generated",
            answer="AI 整理后的比赛镜像下载说明。",
            model=self.model,
        )


class WorkbenchWebWechatBridgeTest(unittest.TestCase):
    def test_debug_listener_event_is_pending_with_confidences_and_unmatched_reasons(self):
        event = ChatEvent(
            "evt-debug-unmatched",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-07-25 12:00:00",
            "今天天气不错",
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
            state.wechat_listener = FakeListener([event])

            payload = state.poll_wechat_once()
            item = payload["items"][0]

        self.assertEqual(item["review_status"], "pending_review")
        self.assertEqual(item["match_status"], "unmatched")
        self.assertEqual(
            item["unmatched_reasons"],
            [
                "missing_question_mark",
                "missing_keyword",
                "missing_agent_mention",
            ],
        )
        self.assertIn("confidence", item)
        self.assertIn("semantic_confidence", item)
        self.assertIn("faq_confidence", item)
        self.assertIn("rag_confidence", item)

    def test_unreplied_listener_event_survives_api_state_restart(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-persisted-pending",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-07-23 12:00:00",
            "XPUOJ测评 MoE 耗时减少了但是分数反而降低了？",
            "text",
            "weflow_live",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "wechat_bridge_config.json"
            first = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )
            first.configure_wechat(
                {
                    "base_url": "http://127.0.0.1:5031",
                    "token_env": "WEFLOW_API_TOKEN",
                    "group_name": "测试群",
                    "session_id": "",
                    "keywords": ["测试"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            first.wechat_listener = FakeListener([event])

            first_payload = first.poll_wechat_once()
            restarted = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )
            restored = restarted.list_items()["items"]

        self.assertEqual(first_payload["items"][0]["status"], "待审核")
        self.assertEqual([item["question"] for item in restored], [event.content])
        self.assertEqual(restored[0]["status"], "待审核")

    def test_successfully_replied_listener_event_moves_to_history_and_keeps_legacy_inbox(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-persisted-replied",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-07-23 12:01:00",
            "线下夏令营在哪？",
            "text",
            "weflow_live",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "wechat_bridge_config.json"
            first = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )
            first.configure_wechat(
                {
                    "base_url": "http://127.0.0.1:5031",
                    "token_env": "WEFLOW_API_TOKEN",
                    "group_name": "测试群",
                    "session_id": "",
                    "keywords": ["测试"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            first.paste_adapter = FakePasteAdapter()
            first.wechat_listener = FakeListener([event])

            first.poll_wechat_once()
            inbox_path = root / "workbench_inbox.jsonl"
            restarted = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )

            self.assertTrue(inbox_path.exists())
            self.assertIn(event.event_id, inbox_path.read_text(encoding="utf-8"))
            self.assertEqual(restarted.list_items()["items"], [])
            history = restarted.list_items(scope="all")["items"]
            self.assertEqual(history[0]["review_status"], "sent")

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

    def test_concurrent_item_refresh_and_listener_start_do_not_overlap_polls(self):
        import threading
        import time

        from summer_camp_agent.wechat_live_listener import ListenerPollResult

        class OverlapDetectingListener:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def poll_once(self, *, include_seen=False):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                try:
                    time.sleep(0.05)
                    return ListenerPollResult("ok", "ok", [])
                finally:
                    with self.lock:
                        self.active -= 1

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            listener = OverlapDetectingListener()
            state.wechat_listener = listener
            state.wechat_listener_running = True
            barrier = threading.Barrier(3)
            threads = [
                threading.Thread(target=lambda: (barrier.wait(), state.poll_wechat_once())),
                threading.Thread(target=lambda: (barrier.wait(), state.list_items())),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=2)

        self.assertEqual(listener.max_active, 1)

    def test_item_refresh_waits_until_manual_auto_publish_is_persisted(self):
        import threading

        from summer_camp_agent.wechat_live_listener import ListenerPollResult
        from summer_camp_agent.workbench_models import ChatEvent

        class BlockingPasteAdapter(FakePasteAdapter):
            def __init__(self):
                super().__init__()
                self.entered = threading.Event()
                self.release = threading.Event()

            def send_to_wechat_foreground(self, text, target_group_name=""):
                self.entered.set()
                self.release.wait(timeout=2)
                return super().send_to_wechat_foreground(text, target_group_name)

        class PollRecordingListener(ReplyAwareFakeListener):
            def __init__(self):
                super().__init__([])
                self.polled = threading.Event()

            def poll_once(self, *, include_seen=False):
                self.polled.set()
                return ListenerPollResult("ok", "ok", [])

        event = ChatEvent(
            "evt-manual-publish-lock",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-07-22 23:00:00",
            "报名时间是什么时候？",
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
                    "keywords": ["报名"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            adapter = BlockingPasteAdapter()
            listener = PollRecordingListener()
            state.paste_adapter = adapter
            state.wechat_listener = listener
            state.wechat_listener_running = True
            item = state.session.process_event(event)
            state.items = [item]
            publish_thread = threading.Thread(
                target=lambda: state.publish_reply(event.event_id, item.reply_decision.reply)
            )
            refresh_thread = threading.Thread(target=state.list_items)
            publish_thread.start()
            self.assertTrue(adapter.entered.wait(timeout=1))
            refresh_thread.start()
            self.assertFalse(listener.polled.wait(timeout=0.05))
            adapter.release.set()
            publish_thread.join(timeout=2)
            refresh_thread.join(timeout=2)

        self.assertTrue(listener.polled.is_set())
        self.assertEqual(listener.replied_event_ids, [event.event_id])

    def test_poll_wechat_once_auto_publishes_faq_in_auto_send_mode(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-live-auto-faq",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-07-21 10:00:00",
            "报名入口在哪里？",
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
                    "keywords": ["报名"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": False,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            state.paste_adapter = FakePasteAdapter()
            state.wechat_listener = FakeListener([event])

            payload = state.poll_wechat_once()
            history = state.list_items(scope="all")["items"]

            self.assertEqual(payload["items"], [])
            self.assertEqual(history[0]["mode"], "auto_send")
            self.assertEqual(state.paste_adapter.sent, [history[0]["reply"]])
            self.assertIn("auto_sent_to_wechat", (root / "logs.jsonl").read_text(encoding="utf-8"))

    def test_successful_auto_publish_marks_listener_event_as_replied(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-mark-replied",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-07-21 10:00:00",
            "报名入口在哪里？",
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
                    "keywords": ["报名"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": False,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            state.paste_adapter = FakePasteAdapter()
            listener = ReplyAwareFakeListener([event])
            state.wechat_listener = listener

            state.poll_wechat_once()
            sent_reply = state.list_items(scope="all")["items"][0]["reply"]

        self.assertEqual(listener.replied_event_ids, ["evt-mark-replied"])
        self.assertEqual(listener.sent_replies, [sent_reply])

    def test_repeated_publish_for_same_event_is_blocked_after_first_send(self):
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
                    "keywords": ["报名"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": False,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            state.paste_adapter = FakePasteAdapter()
            listener = ReplyAwareFakeListener([])
            state.wechat_listener = listener
            item = state.ask("报名入口在哪里？")["item"]

            state.publish_reply(item["event_id"], item["reply"])
            with self.assertRaisesRegex(ValueError, "已回复"):
                state.publish_reply(item["event_id"], item["reply"])

        self.assertEqual(state.paste_adapter.sent, [item["reply"]])

    def test_background_listener_poll_does_not_include_seen_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            listener = IncludeSeenRecordingListener()
            state.wechat_listener = listener
            state.wechat_listener_running = True

            state.list_items()

        self.assertEqual(listener.include_seen_values, [False])

    def test_poll_wechat_once_auto_publishes_official_rag_answer(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-live-auto-rag",
            "sha256:group",
            "测试群",
            "成员002",
            "student",
            "2026-07-21 10:01:00",
            "请问能否公开下载比赛镜像？",
            "text",
            "weflow_live",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=root / "wechat_bridge_config.json",
                rag_answer_generator=FakeRagAnswerGenerator(),
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
                    "show_debug_config": False,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            state.paste_adapter = FakePasteAdapter()
            state.wechat_listener = FakeListener([event])

            payload = state.poll_wechat_once()
            history = state.list_items(scope="all")["items"]

        self.assertEqual(payload["items"], [])
        self.assertEqual(history[0]["intent"], "rag.document")
        self.assertEqual(history[0]["mode"], "auto_send")
        self.assertEqual(history[0]["generation_mode"], "rag_ai")
        self.assertEqual(history[0]["generation_model"], "fake-model")
        self.assertEqual(history[0]["generation_error"], "")
        self.assertEqual(state.paste_adapter.sent, [history[0]["reply"]])
        self.assertEqual(
            history[0]["reply"],
            "AI 整理后的比赛镜像下载说明。",
        )

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

    def test_configure_wechat_keeps_existing_review_snapshot_stable(self):
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

        self.assertEqual(initial["item"]["status"], "待审核")
        self.assertEqual(initial["item"]["match_status"], "unmatched")
        self.assertEqual(payload["items"][0]["match_status"], "unmatched")
        self.assertEqual(payload["items"][0]["matched_keywords"], [])

    def test_paste_reply_logs_fill_but_not_confirmed_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.paste_adapter = FakePasteAdapter()
            item = state.ask("报名入口在哪里？")["item"]

            result = state.paste_reply(item["event_id"], item["reply"])

            self.assertEqual(result["paste_action"], "filled_verified")
            self.assertEqual(result["target_status"], "matched")
            self.assertEqual(result["input_status"], "focused")
            self.assertEqual(result["verification_status"], "matched")
            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("filled_verified", log_text)
            self.assertNotIn("operator_confirmed_sent", log_text)

    def test_paste_reply_auto_send_mode_still_requires_operator_confirmation(self):
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
                    "keywords": ["报名"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": False,
                    "send_mode": "auto_send",
                }
            )
            state.paste_adapter = FakePasteAdapter()
            item = state.ask("报名入口在哪里？")["item"]

            result = state.paste_reply(item["event_id"], item["reply"])

            self.assertEqual(result["paste_action"], "filled_verified")
            self.assertEqual(state.paste_adapter.pasted, [item["reply"]])
            self.assertEqual(state.paste_adapter.sent, [])
            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("filled_verified", log_text)
            self.assertNotIn("auto_sent_to_wechat", log_text)
            self.assertNotIn("operator_confirmed_sent", log_text)

    def test_publish_reply_requires_auto_send_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=root / "wechat_bridge_config.json",
            )
            state.paste_adapter = FakePasteAdapter()
            item = state.ask("报名入口在哪里？")["item"]

            with self.assertRaisesRegex(ValueError, "自动发送"):
                state.publish_reply(item["event_id"], item["reply"])

        self.assertEqual(state.paste_adapter.sent, [])

    def test_publish_reply_auto_sends_and_logs(self):
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
                    "keywords": ["报名"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": False,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            state.paste_adapter = FakePasteAdapter()
            item = state.ask("报名入口在哪里？")["item"]

            result = state.publish_reply(item["event_id"], item["reply"])
            pending = state.list_items()["items"]
            listed = state.list_items(scope="all")["items"][0]

            self.assertEqual(result["paste_action"], "sent_verified")
            self.assertEqual(state.paste_adapter.sent, [item["reply"]])
            self.assertEqual(pending, [])
            self.assertTrue(listed["replied"])
            self.assertEqual(listed["status"], "已发送")
            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("auto_sent_to_wechat", log_text)
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

        self.assertEqual(payload["paste_action"], "filled_verified")
        self.assertEqual(payload["target_status"], "matched")
        self.assertEqual(payload["input_status"], "focused")
        self.assertEqual(payload["verification_status"], "matched")
        self.assertIn("手动发送", payload["message"])

    def test_list_items_polls_running_listener_and_deduplicates_events(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-live-refresh",
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
            state.wechat_listener_running = True

            first = state.list_items()
            second = state.list_items()

        self.assertEqual(first["items"][0]["event_id"], "evt-live-refresh")
        self.assertEqual(len(second["items"]), 1)
        self.assertEqual(state.wechat_listener.poll_count, 2)


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
    def test_vision_capture_auto_publishes_faq_in_auto_send_mode(self):
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
                    "keywords": ["报名"],
                    "poll_interval_seconds": 5,
                    "enabled": True,
                    "show_debug_config": False,
                    "send_mode": "auto_send",
                    "debug_review_mode": False,
                }
            )
            state.paste_adapter = FakePasteAdapter()
            state.vision_observer = FakeVisionObserver()
            state.vision_window_backend = FakeVisionWindowBackend()

            payload = state.capture_vision_once()
            history = state.list_items(scope="all")["items"]

        self.assertEqual(payload["items"], [])
        self.assertEqual(history[0]["mode"], "auto_send")
        self.assertEqual(state.paste_adapter.sent, [history[0]["reply"]])

    def test_start_vision_polls_weflow_messages_first(self):
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "evt-start-observe",
            "sha256:group",
            "测试群",
            "成员001",
            "student",
            "2026-07-02 20:00:00",
            "报名入口在哪里？",
            "text",
            "weflow_live",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.wechat_listener = FakeListener([event])
            state.vision_observer = FakeVisionObserver()
            state.vision_window_backend = FakeVisionWindowBackend(status="not_found", message="不应先走截图识别")

            payload = state.start_vision()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["items"][0]["event_id"], "evt-start-observe")
        self.assertEqual(payload["items"][0]["source"], "weflow_live")
        self.assertTrue(payload["vision"]["running"])

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

    def test_stop_vision_stops_live_listener_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchApiState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.vision_observer = FakeVisionObserver()
            state.wechat_listener = FakeListener([])
            state.wechat_listener_running = True

            state.stop_vision()

        self.assertFalse(state.wechat_listener_running)


if __name__ == "__main__":
    unittest.main()
