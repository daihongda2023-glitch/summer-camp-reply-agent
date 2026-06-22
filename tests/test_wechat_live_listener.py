import unittest

from summer_camp_agent.wechat_bridge_config import ListenerStateStore, WeChatBridgeConfig
from summer_camp_agent.wechat_live_listener import WeFlowLiveListener
from summer_camp_agent.weflow_import import WeFlowSession


class FakeClient:
    def __init__(self, sessions=None):
        self.search_calls = []
        self.pull_calls = []
        self.sessions = (
            [WeFlowSession(id="room@chatroom", name="测试群", type="group")] if sessions is None else sessions
        )

    def search_sessions(self, keyword):
        self.search_calls.append(keyword)
        return self.sessions

    def pull_messages(self, session_id, *, since, end, limit, offset):
        self.pull_calls.append((session_id, since, end, limit, offset))
        return {
            "meta": {"groupId": "room@chatroom"},
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
        )

        first = listener.poll_once()
        second = listener.poll_once()

        self.assertEqual(len(first.events), 1)
        self.assertEqual(second.events, [])
        self.assertEqual(second.status, "ok")

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
