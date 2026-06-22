import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.wechat_bridge_config import (
    DEFAULT_GROUP_NAME,
    ListenerState,
    ListenerStateStore,
    WeChatBridgeConfig,
    WeChatBridgeConfigError,
    WeChatBridgeConfigStore,
)


class WeChatBridgeConfigTest(unittest.TestCase):
    def test_default_config_uses_target_weflow_group(self):
        self.assertEqual(WeChatBridgeConfig().group_name, DEFAULT_GROUP_NAME)
        self.assertEqual(WeChatBridgeConfig.from_dict({}).group_name, DEFAULT_GROUP_NAME)

    def test_config_from_dict_rejects_remote_base_url(self):
        with self.assertRaisesRegex(WeChatBridgeConfigError, "只允许连接本机"):
            WeChatBridgeConfig.from_dict({"base_url": "https://example.com", "group_name": "测试群"})

    def test_config_store_round_trips_without_token_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wechat_bridge_config.json"
            store = WeChatBridgeConfigStore(path)
            config = WeChatBridgeConfig(
                base_url="http://127.0.0.1:5031",
                token_env="WEFLOW_API_TOKEN",
                group_name="测试群",
                session_id="",
                keywords=["报名", "住宿"],
                poll_interval_seconds=5,
                enabled=True,
            )

            store.save(config)
            loaded = store.load()
            raw = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(loaded.group_name, "测试群")
        self.assertEqual(loaded.keywords, ["报名", "住宿"])
        self.assertEqual(raw["token_env"], "WEFLOW_API_TOKEN")
        self.assertNotIn("token", raw)
        self.assertNotIn("access_token", raw)
        self.assertNotIn("secret-token", json.dumps(raw, ensure_ascii=False))

    def test_config_from_dict_defaults_debug_config_to_false(self):
        config = WeChatBridgeConfig.from_dict({"group_name": "test group"})

        self.assertFalse(config.show_debug_config)

    def test_config_store_round_trips_debug_config_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wechat_bridge_config.json"
            store = WeChatBridgeConfigStore(path)
            config = WeChatBridgeConfig(
                group_name="test group",
                session_id="room@chatroom",
                keywords=["signup"],
                poll_interval_seconds=5,
                enabled=True,
                show_debug_config=True,
            )

            store.save(config)
            loaded = store.load()
            raw = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(loaded.show_debug_config)
        self.assertTrue(raw["show_debug_config"])

    def test_listener_state_store_hashes_session_and_caps_seen_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listener_state.json"
            store = ListenerStateStore(path, max_seen_ids=3)
            state = ListenerState.empty()
            state = state.with_seen_event("sha256:1")
            state = state.with_seen_event("sha256:2")
            state = state.with_seen_event("sha256:3")
            state = state.with_seen_event("sha256:4")
            state = state.with_session_id("room@chatroom")

            store.save(state)
            loaded = store.load()
            raw_text = path.read_text(encoding="utf-8")

        self.assertEqual(loaded.seen_event_ids, ["sha256:2", "sha256:3", "sha256:4"])
        self.assertTrue(loaded.session_id_hash.startswith("sha256:"))
        self.assertNotIn("room@chatroom", raw_text)

    def test_gitignore_covers_wechat_bridge_config(self):
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"

        self.assertIn("data/wechat_bridge_config.json", gitignore.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
