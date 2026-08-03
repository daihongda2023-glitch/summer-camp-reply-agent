import unittest

from summer_camp_agent.workbench_models import ChatEvent, GroupConfig
from summer_camp_agent.workbench_trigger import TriggerEngine, unmatched_reason_codes


class WorkbenchTriggerTest(unittest.TestCase):
    def make_event(self, content: str, raw_type: str = "text") -> ChatEvent:
        return ChatEvent(
            event_id="evt-1",
            group_id_hash="sha256:group",
            group_name="夏令营咨询群",
            sender_alias="成员001",
            sender_role="student",
            message_time="2026-06-21 10:00:00",
            content=content,
            raw_type=raw_type,
            source="manual",
        )

    def test_triggers_on_agent_mention(self):
        config = GroupConfig(group_name="夏令营咨询群", agent_mentions=["@Agent"], keywords=["报名"])

        decision = TriggerEngine(config).decide(self.make_event("@Agent 报名入口在哪里？"))

        self.assertTrue(decision.should_process)
        self.assertIn("mention", decision.reasons)

    def test_triggers_on_keyword(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["住宿"])

        decision = TriggerEngine(config).decide(self.make_event("住宿怎么安排"))

        self.assertTrue(decision.should_process)
        self.assertEqual(decision.matched_keywords, ["住宿"])

    def test_triggers_on_question_mark_with_camp_term(self):
        config = GroupConfig(group_name="夏令营咨询群")

        decision = TriggerEngine(config).decide(self.make_event("夏令营什么时候开始？"))

        self.assertTrue(decision.should_process)
        self.assertIn("question_mark", decision.reasons)

    def test_triggers_on_any_question_mark_without_camp_term_or_keyword(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])

        for content in ("这个怎么处理？", "这个怎么处理?"):
            with self.subTest(content=content):
                decision = TriggerEngine(config).decide(self.make_event(content))
                self.assertTrue(decision.should_process)
                self.assertIn("question_mark", decision.reasons)
                self.assertEqual(decision.matched_keywords, [])

    def test_triggers_on_competition_image_question_without_keyword(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["测试"])

        decision = TriggerEngine(config).decide(self.make_event("请问能否公开下载比赛镜像？"))

        self.assertTrue(decision.should_process)
        self.assertIn("question_mark", decision.reasons)
        self.assertEqual(decision.matched_keywords, [])

    def test_triggers_on_common_question_words_without_question_mark(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])
        question_words = [
            "为什么",
            "为何",
            "怎么回事",
            "什么",
            "是啥",
            "有哪些",
            "哪些",
            "哪个",
            "怎么",
            "怎样",
            "如何",
            "怎么办",
            "哪里",
            "哪儿",
            "在哪",
            "什么地方",
            "什么时候",
            "何时",
            "多久",
            "几点",
            "哪天",
            "多少",
            "几个",
            "几次",
            "几天",
            "谁",
            "找谁",
            "联系谁",
            "是否",
            "是不是",
            "有没有",
            "能否",
            "可否",
            "可以吗",
            "能不能",
            "要不要",
            "需不需要",
            "是否需要",
            "怎么样",
            "进展如何",
            "什么情况",
            "咋",
            "咋办",
            "咋回事",
            "啥",
            "有啥",
            "在哪儿",
        ]

        for question_word in question_words:
            with self.subTest(question_word=question_word):
                decision = TriggerEngine(config).decide(
                    self.make_event(f"{question_word}处理")
                )
                self.assertTrue(decision.should_process)
                self.assertIn("question_word", decision.reasons)
                self.assertEqual(decision.matched_keywords, [])

    def test_no_reply_expressions_do_not_trigger_question_words(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])

        for content in (
            "没什么问题",
            "没什么问题了。",
            "没事了",
            "不用了",
            "不需要了",
            "收到",
            "知道了",
            "明白了",
        ):
            with self.subTest(content=content):
                decision = TriggerEngine(config).decide(self.make_event(content))
                self.assertFalse(decision.should_process)

    def test_no_reply_phrase_does_not_hide_a_later_question(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])

        decision = TriggerEngine(config).decide(
            self.make_event("没什么问题，不过怎么联系老师")
        )

        self.assertTrue(decision.should_process)
        self.assertIn("question_word", decision.reasons)

    def test_ignores_unrelated_chat(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])

        decision = TriggerEngine(config).decide(self.make_event("收到，谢谢老师"))

        self.assertFalse(decision.should_process)
        self.assertEqual(decision.reasons, [])

    def test_reports_all_unmatched_reason_codes_for_unrelated_chat(self):
        config = GroupConfig(
            group_name="夏令营咨询群",
            keywords=["报名"],
            agent_mentions=["@夏令营助手"],
        )
        event = self.make_event("今天天气不错")
        decision = TriggerEngine(config).decide(event)

        self.assertEqual(
            unmatched_reason_codes(event, config, decision),
            [
                "missing_question_mark",
                "missing_question_word",
                "missing_keyword",
                "missing_agent_mention",
            ],
        )

    def test_ignores_media_message(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])

        decision = TriggerEngine(config).decide(self.make_event("[图片]", raw_type="image"))

        self.assertFalse(decision.should_process)


if __name__ == "__main__":
    unittest.main()
