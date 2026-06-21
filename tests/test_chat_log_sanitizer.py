import unittest

from summer_camp_agent.chat_log_sanitizer import (
    AliasRegistry,
    SanitizedMessage,
    build_sanitized_message,
    content_matches_keywords,
    hash_identifier,
    sanitize_content,
)


class ChatLogSanitizerTest(unittest.TestCase):
    def test_sanitize_content_masks_common_personal_info(self):
        content = "手机号 13800138000，邮箱 a@test.com，身份证 11010119900307893X，链接 https://example.com/a?token=abc"

        sanitized = sanitize_content(content)

        self.assertIn("[手机号]", sanitized)
        self.assertIn("[邮箱]", sanitized)
        self.assertIn("[身份证]", sanitized)
        self.assertIn("https://example.com", sanitized)
        self.assertNotIn("13800138000", sanitized)
        self.assertNotIn("token=abc", sanitized)

    def test_keyword_matching_returns_unique_hits(self):
        hits = content_matches_keywords("报名入口在哪里，怎么报名？", ["报名", "住宿", "报名"])

        self.assertEqual(hits, ["报名"])

    def test_alias_registry_is_stable_per_sender(self):
        registry = AliasRegistry()

        self.assertEqual(registry.alias_for("wxid_a"), "成员001")
        self.assertEqual(registry.alias_for("wxid_b"), "成员002")
        self.assertEqual(registry.alias_for("wxid_a"), "成员001")

    def test_hash_identifier_does_not_return_raw_value(self):
        digest = hash_identifier("wxid_secret")

        self.assertTrue(digest.startswith("sha256:"))
        self.assertNotIn("wxid_secret", digest)

    def test_build_sanitized_message_filters_unmatched_keywords(self):
        registry = AliasRegistry()

        message = build_sanitized_message(
            source="weflow_api",
            group_name="测试群",
            group_id="room@chatroom",
            message_time="2026-06-20 10:21:00",
            sender_id="wxid_a",
            content="今天午饭吃什么？",
            keywords=["报名"],
            platform_message_id="123",
            raw_type=0,
            alias_registry=registry,
        )

        self.assertIsNone(message)

    def test_build_sanitized_message_outputs_safe_fields(self):
        registry = AliasRegistry()

        message = build_sanitized_message(
            source="weflow_api",
            group_name="测试群",
            group_id="room@chatroom",
            message_time="2026-06-20 10:21:00",
            sender_id="wxid_a",
            content="报名入口发一下，手机号 13800138000",
            keywords=["报名"],
            platform_message_id="123",
            raw_type=0,
            alias_registry=registry,
        )

        self.assertIsInstance(message, SanitizedMessage)
        self.assertEqual(message.sender_alias, "成员001")
        self.assertEqual(message.matched_keywords, ["报名"])
        self.assertIn("[手机号]", message.content)
        self.assertNotIn("wxid_a", message.to_dict().values())


if __name__ == "__main__":
    unittest.main()
