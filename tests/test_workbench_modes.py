import unittest

from summer_camp_agent.review import ReviewCard
from summer_camp_agent.workbench_models import GroupConfig, TriggerDecision
from summer_camp_agent.workbench_modes import ReplyModeController


class WorkbenchModesTest(unittest.TestCase):
    def test_semi_auto_turns_auto_reply_into_draft(self):
        config = GroupConfig(group_name="咨询群", mode="semi_auto")
        card = ReviewCard(
            original_question="报名入口在哪里？",
            recommendation="send",
            available_actions=[],
            action="auto_reply",
            reply="报名入口为...",
            intent="registration.link",
            source="FAQ",
            confidence=0.96,
        )

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["keyword"], ["报名"]), card)

        self.assertEqual(decision.mode, "draft")
        self.assertTrue(decision.requires_review)

    def test_auto_mode_allows_whitelisted_high_confidence_reply(self):
        config = GroupConfig(group_name="咨询群", mode="auto", auto_reply_intents=["registration.link"])
        card = ReviewCard(
            original_question="报名入口在哪里？",
            recommendation="send",
            available_actions=[],
            action="auto_reply",
            reply="报名入口为...",
            intent="registration.link",
            source="FAQ",
            confidence=0.96,
        )

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["keyword"], ["报名"]), card)

        self.assertEqual(decision.mode, "auto_send")
        self.assertFalse(decision.requires_review)

    def test_auto_mode_sends_faq_reply_without_intent_whitelist(self):
        config = GroupConfig(group_name="咨询群", mode="auto", auto_reply_intents=["registration.link"])
        card = ReviewCard(
            original_question="住宿怎么安排？",
            recommendation="send",
            available_actions=[],
            action="auto_reply",
            reply="住宿统一安排",
            intent="cost.accommodation",
            source="FAQ",
            confidence=0.96,
        )

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["keyword"], ["住宿"]), card)

        self.assertEqual(decision.mode, "auto_send")
        self.assertFalse(decision.requires_review)

    def test_auto_mode_sends_strong_official_rag_reply(self):
        config = GroupConfig(group_name="咨询群", mode="auto")
        card = ReviewCard(
            original_question="请问能否公开下载比赛镜像？",
            recommendation="send",
            available_actions=[],
            action="auto_reply",
            reply="可以通过沐曦开发者社区下载。",
            intent="rag.document",
            source="GitLink Issue #19",
            confidence=0.84,
        )

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["question_mark"], []), card)

        self.assertEqual(decision.mode, "auto_send")
        self.assertFalse(decision.requires_review)

    def test_auto_mode_sends_community_rag_when_rag_has_a_usable_reply(self):
        config = GroupConfig(group_name="咨询群", mode="auto")
        card = ReviewCard(
            original_question="cmake 构建失败怎么办？",
            recommendation="mark_pending",
            available_actions=[],
            action="suggested_reply",
            reply="以下是社区经验，仅供参考。",
            intent="rag.document",
            source="GitLink 社区 Issue",
            confidence=0.95,
            generation_mode="rag_community",
        )

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["keyword"], ["构建"]), card)

        self.assertEqual(decision.mode, "auto_send")
        self.assertFalse(decision.requires_review)

    def test_auto_mode_sends_faq_even_when_legacy_trigger_does_not_match(self):
        config = GroupConfig(group_name="咨询群", mode="auto")
        card = ReviewCard(
            original_question="线下地点",
            recommendation="send",
            available_actions=[],
            action="auto_reply",
            reply="地点为上海交通大学、沐曦股份。",
            intent="offline.location",
            source="FAQ",
            confidence=1.0,
            generation_mode="faq",
        )

        decision = ReplyModeController(config).decide(TriggerDecision(False, [], []), card)

        self.assertEqual(decision.mode, "auto_send")
        self.assertFalse(decision.requires_review)

    def test_auto_mode_marks_pending_when_faq_and_rag_both_miss(self):
        config = GroupConfig(group_name="咨询群", mode="auto")
        card = ReviewCard(
            original_question="今天天气不错",
            recommendation="mark_pending",
            available_actions=[],
            action="needs_info",
            reply="当前资料没有明确说明。",
            reason="unknown",
            generation_mode="needs_info",
        )

        decision = ReplyModeController(config).decide(TriggerDecision(False, [], []), card)

        self.assertEqual(decision.mode, "mark_pending")
        self.assertTrue(decision.requires_review)

    def test_human_fallback_is_escalated(self):
        config = GroupConfig(group_name="咨询群", mode="auto", auto_reply_intents=["registration.link"])
        card = ReviewCard(
            original_question="我被录取了吗？",
            recommendation="escalate",
            available_actions=[],
            action="human_fallback",
            reply="请转人工",
            reason="personal_status",
        )

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["question_mark"], []), card)

        self.assertEqual(decision.mode, "escalate")
        self.assertEqual(decision.reason, "personal_status")


if __name__ == "__main__":
    unittest.main()
