import unittest
from datetime import date

from summer_camp_agent.engine import AnswerEngine
from summer_camp_agent.knowledge import KnowledgeBase


def make_engine(today=date(2026, 6, 20)):
    kb = KnowledgeBase.from_default()
    return AnswerEngine(kb, today=today)


class AnswerEngineTest(unittest.TestCase):
    def test_answers_registration_link_from_seed_faq(self):
        result = make_engine().answer("报名入口在哪里？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "registration.link")
        self.assertIn("https://v.wjx.cn/vm/r9BqUzR.aspx#", result.reply)
        self.assertIn("招募文章", result.source)

    def test_returns_miss_for_unknown_question_without_claiming_recorded(self):
        result = make_engine().answer("营服是什么颜色？")

        self.assertEqual(result.action, "needs_info")
        self.assertIn("当前资料还没有明确说明", result.reply)
        self.assertNotIn("已记录", result.reply)

    def test_escalates_personal_selection_result(self):
        result = make_engine().answer("老师，我被录取了吗？能帮我查下面试结果吗？")

        self.assertEqual(result.action, "human_fallback")
        self.assertEqual(result.reason, "personal_status")
        self.assertIn("个人报名状态、录取结果或面试结果", result.reply)

    def test_escalates_assignment_answer_request(self):
        result = make_engine().answer("作业代码跑不通，能直接帮我改出答案吗？")

        self.assertEqual(result.action, "human_fallback")
        self.assertEqual(result.reason, "technical_assignment")
        self.assertIn("技术作业", result.reply)

    def test_expired_auto_reply_is_not_sent(self):
        result = make_engine(today=date(2026, 7, 16)).answer("报名入口在哪里？")

        self.assertEqual(result.action, "needs_info")
        self.assertIn("当前资料还没有明确说明", result.reply)


if __name__ == "__main__":
    unittest.main()
