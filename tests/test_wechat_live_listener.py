from datetime import datetime, timedelta
import unittest

from summer_camp_agent.wechat_bridge_config import ListenerStateStore, WeChatBridgeConfig
from summer_camp_agent.wechat_live_listener import WeFlowLiveListener
from summer_camp_agent.weflow_import import WeFlowSession


class FakeClient:
    def __init__(self, sessions=None, messages=None):
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

    def search_sessions(self, keyword):
        self.search_calls.append(keyword)
        return self.sessions

    def pull_messages(self, session_id, *, since, end, limit, offset):
        self.pull_calls.append((session_id, since, end, limit, offset))
        return {
            "meta": {"groupId": "room@chatroom"},
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
    def test_poll_once_returns_new_chat_events_and_persists_seen_ids(self):
        store = MemoryStateStore()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(group_name="测试群", keywords=["报名"]),
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
            WeChatBridgeConfig(group_name="测试群", keywords=["报名"]),
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

    def test_poll_once_requests_only_the_last_hour(self):
        now = datetime(2026, 6, 22, 12, 0, 0)
        fake_client = FakeClient()
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(group_name="测试群", keywords=["报名"]),
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
            WeChatBridgeConfig(group_name="测试群", keywords=["报名"]),
            state_store=MemoryStateStore(),
            client=fake_client,
            token="fake-token",
            clock=lambda: now,
        )

        result = listener.poll_once()

        self.assertEqual([event.content for event in result.events], ["报名入口在哪里？"])
        self.assertEqual(result.events[0].sender_alias, "成员001")

    def test_poll_once_reports_missing_token(self):
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(group_name="测试群", token_env="MISSING_WEFLOW_TOKEN"),
            state_store=MemoryStateStore(),
            client=FakeClient(),
            token="",
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "error")
        self.assertIn("缺少 MISSING_WEFLOW_TOKEN", result.message)

    def test_poll_once_reports_group_not_found(self):
        listener = WeFlowLiveListener(
            WeChatBridgeConfig(group_name="不存在的群"),
            state_store=MemoryStateStore(),
            client=FakeClient(sessions=[]),
            token="fake-token",
        )

        result = listener.poll_once()

        self.assertEqual(result.status, "error")
        self.assertIn("没有找到匹配群聊：不存在的群", result.message)


if __name__ == "__main__":
    unittest.main()
