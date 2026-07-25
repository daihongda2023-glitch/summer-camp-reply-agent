from datetime import datetime, timedelta
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from summer_camp_agent.wechat_bridge_config import ListenerStateStore, WeChatBridgeConfig
from summer_camp_agent.wechat_live_listener import WeFlowLiveListener
from summer_camp_agent.weflow_import import WeFlowSession


class FakeClient:
    def __init__(self, sessions=None, messages=None, members=None):
        self.search_calls = []
        self.pull_calls = []
        self.sessions = (
            [WeFlowSession(id="room@chatroom", name="测试群", type="group")] if sessions is None else sessions
        )
        self.messages = (
            [
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
            ]
            if messages is None
            else messages
        )
        self.members = [] if members is None else members

    def search_sessions(self, keyword):
        self.search_calls.append(keyword)
        return self.sessions

    def pull_messages(self, session_id, *, since, end, limit, offset):
        self.pull_calls.append((session_id, since, end, limit, offset))
        return {
            "meta": {"groupId": "room@chatroom"},
            "members": self.members,
            "messages": self.messages,
            "sync": {"hasMore": False},
        }


class MemoryStateStore(ListenerStateStore):
    def __init__(self):
        self.state = None

    def load(self):
        from summer_camp_agent.wechat_bridge_config import ListenerState

        return self.state or ListenerState.empty()

    def save(self, state):
        self.state = state


class WeFlowLiveListenerTest(unittest.TestCase):
    def test_debug_review_mode_returns_unmatched_text_message(self):
        now = datetime(2026, 7, 25, 10, 0, 0)
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试群",
                keywords=["报名"],
                debug_review_mode=True,
            ),
            state_store=MemoryStateStore(),
            client=FakeClient(
                messages=[
                    {
                        "sender": "wxid_student",
                        "timestamp": int((now - timedelta(seconds=5)).timestamp()),
                        "type": 0,
                        "content": "今天天气不错",
                        "platformMessageId": "msg-debug",
                    }
                ]
            ),
            token="fake-token",
            clock=lambda: now,
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "ok")
        self.assertEqual(
            [event.content for event in result.events],
            ["今天天气不错"],
        )

    def test_formal_mode_still_filters_unmatched_text_message(self):
        now = datetime(2026, 7, 25, 10, 0, 0)
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试群",
                keywords=["报名"],
                debug_review_mode=False,
            ),
            state_store=MemoryStateStore(),
            client=FakeClient(
                messages=[
                    {
                        "sender": "wxid_student",
                        "timestamp": int((now - timedelta(seconds=5)).timestamp()),
                        "type": 0,
                        "content": "今天天气不错",
                        "platformMessageId": "msg-formal",
                    }
                ]
            ),
            token="fake-token",
            clock=lambda: now,
        )

        self.assertEqual(listener.poll_once().events, [])

    def test_poll_once_ignores_all_messages_from_current_logged_in_account(self):
        now = datetime(2026, 7, 22, 23, 0, 0)
        sent_reply = "TileLang 资料已开放；测试集正在整理中。"
        test_question = "报名时间是什么时候？"
        store = MemoryStateStore()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试工具",
                keywords=["测试"],
                debug_review_mode=False,
            ),
            state_store=store,
            client=FakeClient(
                sessions=[WeFlowSession(id="room@chatroom", name="测试工具", type="group")],
                messages=[
                    {
                        "sender": "wxid_self",
                        "accountName": "我",
                        "timestamp": int((now - timedelta(seconds=10)).timestamp()),
                        "type": 0,
                        "content": sent_reply,
                        "platformMessageId": "msg-self-reply",
                    },
                    {
                        "sender": "wxid_self",
                        "accountName": "我",
                        "timestamp": int((now - timedelta(seconds=5)).timestamp()),
                        "type": 0,
                        "content": test_question,
                        "platformMessageId": "msg-self-question",
                    },
                ],
            ),
            token="fake-token",
            clock=lambda: now,
        )
        listener.mark_replied("evt-original-question", sent_reply)

        result = listener.poll_once()

        self.assertEqual(result.events, [])

    def test_poll_once_ignores_current_account_from_member_identity_when_message_has_no_account_name(self):
        now = datetime(2026, 7, 22, 23, 0, 0)
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试工具",
                keywords=[],
                debug_review_mode=False,
            ),
            state_store=MemoryStateStore(),
            client=FakeClient(
                sessions=[WeFlowSession(id="room@chatroom", name="测试工具", type="group")],
                members=[{"platformId": "wxid_self", "accountName": "我"}],
                messages=[
                    {
                        "sender": "wxid_self",
                        "timestamp": int((now - timedelta(seconds=5)).timestamp()),
                        "type": 0,
                        "content": "这个怎么处理？",
                        "platformMessageId": "msg-self-without-account-name",
                    }
                ],
            ),
            token="fake-token",
            clock=lambda: now,
        )

        result = listener.poll_once()

        self.assertEqual(result.events, [])

    def test_poll_once_never_replays_replied_event_even_when_seen_messages_are_included(self):
        store = MemoryStateStore()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试群",
                keywords=["报名"],
                debug_review_mode=False,
            ),
            state_store=store,
            client=FakeClient(),
            token="fake-token",
            clock=lambda: datetime.fromtimestamp(1781911320) + timedelta(minutes=1),
        )
        first = listener.poll_once()
        replied_event_id = first.events[0].event_id
        from summer_camp_agent.wechat_bridge_config import ListenerState

        store.state = ListenerState.from_dict(
            {
                **store.state.to_dict(),
                "replied_event_ids": [replied_event_id],
            }
        )

        second = listener.poll_once(include_seen=True)

        self.assertEqual(second.events, [])

    def test_poll_once_keeps_question_trigger_even_without_configured_keyword(self):
        now = datetime(2026, 7, 21, 12, 0, 0)
        fake_client = FakeClient(
            messages=[
                {
                    "sender": "wxid_student",
                    "timestamp": int((now - timedelta(minutes=1)).timestamp()),
                    "type": 0,
                    "content": "请问能否公开下载比赛镜像？",
                    "platformMessageId": "msg-image-download",
                }
            ]
        )
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试群",
                keywords=["测试"],
                debug_review_mode=False,
            ),
            state_store=MemoryStateStore(),
            client=fake_client,
            token="fake-token",
            clock=lambda: now,
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "ok")
        self.assertEqual([event.content for event in result.events], ["请问能否公开下载比赛镜像？"])

    def test_poll_once_returns_new_chat_events_and_persists_seen_ids(self):
        store = MemoryStateStore()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试群",
                keywords=["报名"],
                debug_review_mode=False,
            ),
            state_store=store,
            client=FakeClient(),
            token="fake-token",
            clock=lambda: datetime.fromtimestamp(1781911320) + timedelta(minutes=1),
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].content, "报名入口在哪里？")
        self.assertEqual(result.events[0].group_name, "测试群")
        self.assertIn(result.events[0].event_id, store.state.seen_event_ids)
        self.assertTrue(store.state.session_id_hash.startswith("sha256:"))

    def test_poll_once_filters_already_seen_events(self):
        store = MemoryStateStore()
        fake_client = FakeClient()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试群",
                keywords=["报名"],
                debug_review_mode=False,
            ),
            state_store=store,
            client=fake_client,
            token="fake-token",
            clock=lambda: datetime.fromtimestamp(1781911320) + timedelta(minutes=1),
        )

        first = listener.poll_once()
        second = listener.poll_once()

        self.assertEqual(len(first.events), 1)
        self.assertEqual(second.events, [])
        self.assertEqual(second.status, "ok")

    def test_poll_once_can_backfill_seen_unreplied_messages(self):
        store = MemoryStateStore()
        fake_client = FakeClient()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="test group",
                keywords=["报名"],
                debug_review_mode=False,
            ),
            state_store=store,
            client=fake_client,
            token="fake-token",
            clock=lambda: datetime.fromtimestamp(1781911320) + timedelta(minutes=1),
        )

        first = listener.poll_once()
        second = listener.poll_once(include_seen=True)

        self.assertEqual(len(first.events), 1)
        self.assertEqual(len(second.events), 1)
        self.assertEqual(second.events[0].event_id, first.events[0].event_id)

    def test_poll_once_requests_only_the_last_hour(self):
        now = datetime(2026, 6, 22, 12, 0, 0)
        fake_client = FakeClient()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试群",
                keywords=["报名"],
                debug_review_mode=False,
            ),
            state_store=MemoryStateStore(),
            client=fake_client,
            token="fake-token",
            clock=lambda: now,
        )

        listener.poll_once()

        self.assertEqual(fake_client.pull_calls[0][1], int((now - timedelta(hours=1)).timestamp()))

    def test_poll_once_ignores_messages_older_than_one_hour_if_api_returns_them(self):
        now = datetime(2026, 6, 22, 12, 0, 0)
        old_timestamp = int((now - timedelta(hours=2)).timestamp())
        fresh_timestamp = int((now - timedelta(minutes=5)).timestamp())
        fake_client = FakeClient(
            messages=[
                {
                    "sender": "wxid_old",
                    "timestamp": old_timestamp,
                    "type": 0,
                    "content": "报名入口在哪里？",
                    "platformMessageId": "msg-old",
                },
                {
                    "sender": "wxid_fresh",
                    "timestamp": fresh_timestamp,
                    "type": 0,
                    "content": "报名入口在哪里？",
                    "platformMessageId": "msg-fresh",
                },
            ]
        )
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="测试群",
                keywords=["报名"],
                debug_review_mode=False,
            ),
            state_store=MemoryStateStore(),
            client=fake_client,
            token="fake-token",
            clock=lambda: now,
        )

        result = listener.poll_once()

        self.assertEqual([event.content for event in result.events], ["报名入口在哪里？"])
        self.assertEqual(result.events[0].sender_alias, "成员001")

    def test_poll_once_skips_message_replied_by_quote_context(self):
        now = datetime(2026, 6, 22, 12, 0, 0)
        question_timestamp = int((now - timedelta(minutes=20)).timestamp())
        reply_timestamp = int((now - timedelta(minutes=10)).timestamp())
        fake_client = FakeClient(
            messages=[
                {
                    "sender": "student-a",
                    "timestamp": question_timestamp,
                    "type": 0,
                    "content": "signup link?",
                    "platformMessageId": "msg-question",
                },
                {
                    "sender": "teacher",
                    "timestamp": reply_timestamp,
                    "type": 0,
                    "content": "please use the official link",
                    "platformMessageId": "msg-reply",
                    "quoteMessageId": "msg-question",
                },
            ]
        )
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="test group",
                keywords=["signup"],
                debug_review_mode=False,
            ),
            state_store=MemoryStateStore(),
            client=fake_client,
            token="fake-token",
            clock=lambda: now,
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.events, [])

    def test_poll_once_skips_message_replied_by_mentioning_sender(self):
        now = datetime(2026, 6, 22, 12, 0, 0)
        question_timestamp = int((now - timedelta(minutes=20)).timestamp())
        reply_timestamp = int((now - timedelta(minutes=10)).timestamp())
        open_timestamp = int((now - timedelta(minutes=5)).timestamp())
        fake_client = FakeClient(
            messages=[
                {
                    "sender": "student-a",
                    "senderName": "Alice",
                    "timestamp": question_timestamp,
                    "type": 0,
                    "content": "signup link?",
                    "platformMessageId": "msg-replied",
                },
                {
                    "sender": "teacher",
                    "timestamp": reply_timestamp,
                    "type": 0,
                    "content": "@Alice please use the official link",
                    "platformMessageId": "msg-mention-reply",
                },
                {
                    "sender": "student-b",
                    "senderName": "Bob",
                    "timestamp": open_timestamp,
                    "type": 0,
                    "content": "signup deadline?",
                    "platformMessageId": "msg-open",
                },
            ]
        )
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="test group",
                keywords=["signup"],
                debug_review_mode=False,
            ),
            state_store=MemoryStateStore(),
            client=fake_client,
            token="fake-token",
            clock=lambda: now,
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "ok")
        self.assertEqual([event.content for event in result.events], ["signup deadline?"])

    def test_poll_once_reports_missing_token(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "WeFlow-config.json"
            config_path.write_text(json.dumps({"httpApiToken": ""}), encoding="utf-8")
            listener = WeFlowLiveListener(
                WeChatBridgeConfig(
                    group_name="测试群",
                    token_env="MISSING_WEFLOW_TOKEN",
                    debug_review_mode=False,
                ),
                state_store=MemoryStateStore(),
                client=FakeClient(),
                token="",
            )

            with patch.dict("os.environ", {"WEFLOW_CONFIG_PATH": str(config_path)}, clear=True):
                result = listener.poll_once()

        self.assertEqual(result.status, "error")
        self.assertIn("缺少 MISSING_WEFLOW_TOKEN", result.message)

    def test_poll_once_reports_group_not_found(self):
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(
                group_name="不存在的群",
                debug_review_mode=False,
            ),
            state_store=MemoryStateStore(),
            client=FakeClient(sessions=[]),
            token="fake-token",
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "error")
        self.assertIn("没有找到匹配群聊：不存在的群", result.message)


if __name__ == "__main__":
    unittest.main()
