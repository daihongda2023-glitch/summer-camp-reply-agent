import unittest

from summer_camp_agent.workbench_models import ChatEvent, GroupConfig
from summer_camp_agent.workbench_trigger import TriggerEngine


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

    def test_ignores_unrelated_chat(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])

        decision = TriggerEngine(config).decide(self.make_event("收到，谢谢老师"))

        self.assertFalse(decision.should_process)
        self.assertEqual(decision.reasons, [])

    def test_ignores_media_message(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])

        decision = TriggerEngine(config).decide(self.make_event("[图片]", raw_type="image"))

        self.assertFalse(decision.should_process)


if __name__ == "__main__":
    unittest.main()
