import unittest

from summer_camp_agent.wechat_bridge_config import DEFAULT_GROUP_NAME
from summer_camp_agent.wechat_vision import (
    VisionMessage,
    VisionState,
    WeChatVisionObserver,
    WindowsOcrVisionRecognizer,
)


class FakeRecognizer:
    def __init__(self, messages):
        self.messages = messages

    def recognize(self, screenshot):
        return self.messages


class WeChatVisionTest(unittest.TestCase):
    def test_default_observer_uses_windows_ocr_recognizer(self):
        observer = WeChatVisionObserver()

        self.assertIsInstance(observer.recognizer, WindowsOcrVisionRecognizer)

    def test_windows_ocr_recognizer_returns_latest_incoming_chat_line(self):
        recognizer = WindowsOcrVisionRecognizer(
            ocr_runner=lambda _screenshot: {
                "width": 1000,
                "height": 800,
                "lines": [
                    {"text": "联系人", "left": 110, "top": 610, "width": 70, "height": 20},
                    {"text": "20 ： 02", "left": 500, "top": 440, "width": 50, "height": 16},
                    {"text": "报名 入囗 在 哪里 ？", "left": 380, "top": 510, "width": 180, "height": 24},
                    {"text": "好的", "left": 780, "top": 650, "width": 60, "height": 24},
                ],
            }
        )

        messages = recognizer.recognize(b"fake-bmp")

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "报名入口在哪里？")
        self.assertEqual(messages[0].region["x"], 380)

    def test_windows_ocr_recognizer_ignores_non_chat_regions(self):
        recognizer = WindowsOcrVisionRecognizer(
            ocr_runner=lambda _screenshot: {
                "width": 1000,
                "height": 800,
                "lines": [
                    {"text": "联系人", "left": 110, "top": 610, "width": 70, "height": 20},
                    {"text": "22 ： 00", "left": 500, "top": 620, "width": 50, "height": 16},
                    {"text": "我的回复", "left": 780, "top": 650, "width": 80, "height": 24},
                ],
            }
        )

        self.assertEqual(recognizer.recognize(b"fake-bmp"), [])

    def test_windows_ocr_message_id_survives_layout_movement_and_changes_after_new_content(self):
        payload = {
            "width": 1000,
            "height": 800,
            "lines": [{"text": "报名入口在哪里？", "left": 380, "top": 510, "width": 180, "height": 24}],
        }
        recognizer = WindowsOcrVisionRecognizer(ocr_runner=lambda _screenshot: payload)

        first = recognizer.recognize(b"first")[0]
        payload["lines"][0]["top"] = 470
        moved = recognizer.recognize(b"moved")[0]
        payload["lines"][0]["text"] = "住宿怎么安排？"
        recognizer.recognize(b"other")
        payload["lines"][0]["text"] = "报名入口在哪里？"
        repeated = recognizer.recognize(b"repeated")[0]

        self.assertEqual(first.message_id, moved.message_id)
        self.assertNotEqual(first.message_id, repeated.message_id)

    def test_windows_ocr_message_identity_is_isolated_by_conversation(self):
        payload = {
            "width": 1000,
            "height": 800,
            "lines": [{"text": "问题 A", "left": 380, "top": 510, "width": 100, "height": 24}],
        }
        recognizer = WindowsOcrVisionRecognizer(ocr_runner=lambda _screenshot: payload)

        zhang_first = recognizer.recognize(b"a", window_title="张三 - 微信")[0]
        payload["lines"][0]["text"] = "问题 B"
        recognizer.recognize(b"b", window_title="李四 - 微信")
        payload["lines"][0]["text"] = "问题 A"
        zhang_again = recognizer.recognize(b"a-again", window_title="张三 - 微信")[0]

        self.assertEqual(zhang_first.message_id, zhang_again.message_id)

    def test_windows_ocr_distinguishes_two_visible_identical_messages(self):
        payload = {
            "width": 1000,
            "height": 800,
            "lines": [{"text": "收到", "left": 380, "top": 450, "width": 60, "height": 24}],
        }
        recognizer = WindowsOcrVisionRecognizer(ocr_runner=lambda _screenshot: payload)

        first = recognizer.recognize(b"first", window_title="张三 - 微信")[0]
        payload["lines"].append({"text": "收到", "left": 380, "top": 520, "width": 60, "height": 24})
        second = recognizer.recognize(b"second", window_title="张三 - 微信")[0]

        self.assertNotEqual(first.message_id, second.message_id)

    def test_windows_ocr_recognizer_keeps_all_lines_in_latest_message(self):
        recognizer = WindowsOcrVisionRecognizer(
            ocr_runner=lambda _screenshot: {
                "width": 1000,
                "height": 800,
                "lines": [
                    {"text": "第一行", "left": 380, "top": 420, "width": 120, "height": 20},
                    {"text": "第二行", "left": 380, "top": 455, "width": 120, "height": 20},
                    {"text": "第三行", "left": 380, "top": 490, "width": 120, "height": 20},
                ],
            }
        )

        message = recognizer.recognize(b"fake-bmp")[0]

        self.assertEqual(message.content, "第一行第二行第三行")

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
