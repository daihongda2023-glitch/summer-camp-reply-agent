import unittest

from summer_camp_agent.wechat_bridge_config import DEFAULT_GROUP_NAME
from summer_camp_agent.wechat_vision import (
    VisionMessage,
    VisionState,
    WeChatVisionObserver,
)


class FakeRecognizer:
    def __init__(self, messages):
        self.messages = messages

    def recognize(self, screenshot):
        return self.messages


class WeChatVisionTest(unittest.TestCase):
    def test_capture_turns_high_confidence_message_into_chat_event(self):
        observer = WeChatVisionObserver(
            recognizer=FakeRecognizer(
                [
                    VisionMessage(
                        message_id="m1",
                        sender_alias="成员001",
                        content="报名入口在哪里？",
                        message_time="2026-07-02 20:00:00",
                        region={"x": 10, "y": 20, "width": 120, "height": 40},
                        confidence=0.92,
                    )
                ]
            )
        )

        result = observer.capture_once(b"fake", window_title="微信群 - 微信", group_name=DEFAULT_GROUP_NAME)

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].content, "报名入口在哪里？")
        self.assertEqual(result.events[0].source, "wechat_pc_vision")

    def test_capture_deduplicates_seen_messages(self):
        message = VisionMessage(
            message_id="m1",
            sender_alias="成员001",
            content="报名入口在哪里？",
            message_time="2026-07-02 20:00:00",
            region={"x": 10, "y": 20, "width": 120, "height": 40},
            confidence=0.92,
        )
        observer = WeChatVisionObserver(recognizer=FakeRecognizer([message]))

        first = observer.capture_once(b"fake", window_title="微信群 - 微信", group_name=DEFAULT_GROUP_NAME)
        second = observer.capture_once(b"fake", window_title="微信群 - 微信", group_name=DEFAULT_GROUP_NAME)

        self.assertEqual(len(first.events), 1)
        self.assertEqual(len(second.events), 0)
        self.assertEqual(second.message, "未识别到新的高置信消息")

    def test_low_confidence_message_is_blocked(self):
        observer = WeChatVisionObserver(
            recognizer=FakeRecognizer(
                [
                    VisionMessage(
                        message_id="m2",
                        sender_alias="成员002",
                        content="住宿怎么安排？",
                        message_time="2026-07-02 20:01:00",
                        region={"x": 10, "y": 90, "width": 120, "height": 40},
                        confidence=0.41,
                    )
                ]
            )
        )

        result = observer.capture_once(b"fake", window_title="微信群 - 微信", group_name=DEFAULT_GROUP_NAME)

        self.assertEqual(result.status, "low_confidence")
        self.assertEqual(result.events, [])
        self.assertIsInstance(result.vision, VisionState)


if __name__ == "__main__":
    unittest.main()
