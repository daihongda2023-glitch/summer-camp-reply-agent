import unittest
from datetime import date

from summer_camp_agent.engine import AnswerEngine, AnswerResult
from summer_camp_agent.answer_providers import ProviderAnswer
from summer_camp_agent.knowledge import KnowledgeBase
from summer_camp_agent.rag_retriever import RagSearchResult


class FakeRagRetriever:
    def __init__(self, result):
        self.result = result
        self.questions = []

    def retrieve(self, question):
        self.questions.append(question)
        return self.result


class CustomProvider:
    name = "custom"

    def answer(self, question):
        return ProviderAnswer.hit(
            AnswerResult(
                action="suggested_reply",
                reply=f"自定义回复：{question}",
                intent="custom.intent",
                source="custom-provider",
                confidence=0.88,
            )
        )


def make_engine(today=date(2026, 6, 20), rag_retriever=None):
    kb = KnowledgeBase.from_default()
    return AnswerEngine(kb, today=today, rag_retriever=rag_retriever)


class AnswerEngineTest(unittest.TestCase):
    def test_answers_registration_link_from_latest_official_poster_before_deadline(self):
        result = make_engine(today=date(2026, 7, 15)).answer("报名入口在哪里？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "registration.link")
        self.assertIn("https://developer.metax-tech.com/activities/18", result.reply)
        self.assertNotIn("v.wjx.cn", result.reply)
        self.assertIn("官方咨询群海报", result.source)

    def test_answers_latest_course_and_camp_schedule(self):
        cases = [
            ("线上学习和作业什么时候截止？", "2026 年 7 月 20 日"),
            ("课程1在哪里学习？", "https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops"),
            ("作业1在哪里提交？", "https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops/issues/16"),
            ("课程2的作业入口是什么？", "https://www.gitlink.org.cn/metax-maca/op_optimization/issues/12"),
            ("课程直播是什么时间？", "7 月 13 日至 7 月 15 日，每晚 19:00—21:00"),
            ("作业提交账号怎么获得？", "报名时使用的邮箱"),
            ("线下夏令营什么时候在哪里？", "2026 年 8 月 3 日至 8 月 7 日"),
            ("群昵称建议改成什么？", "姓名-学校-年级"),
        ]
        for question, expected in cases:
            with self.subTest(question=question):
                result = make_engine(today=date(2026, 7, 15)).answer(question)
                self.assertEqual(result.action, "auto_reply")
                self.assertIn(expected, result.reply)

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

    def test_expired_registration_uses_explicit_expired_answer(self):
        result = make_engine(today=date(2026, 7, 16)).answer("报名入口在哪里？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "registration.link")
        self.assertIn("报名已于 2026 年 7 月 15 日截止", result.reply)
        self.assertIn("https://developer.metax-tech.com/activities/18", result.reply)

    def test_expired_item_without_expired_answer_is_not_sent(self):
        result = make_engine(today=date(2026, 8, 8)).answer("线下夏令营什么时候举办？")

        self.assertEqual(result.action, "needs_info")
        self.assertIn("当前资料还没有明确说明", result.reply)

    def test_uses_rag_when_faq_does_not_match(self):
        rag_result = RagSearchResult(
            reply="同学你好，营服颜色以后续官方通知为准。",
            source="线下手册 / 物料安排",
            confidence=0.91,
            chunks=[],
            is_strong=True,
        )
        rag = FakeRagRetriever(rag_result)

        result = make_engine(rag_retriever=rag).answer("营服是什么颜色？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "rag.document")
        self.assertEqual(result.reply, rag_result.reply)
        self.assertEqual(result.source, "线下手册 / 物料安排")
        self.assertEqual(result.confidence, 0.91)
        self.assertEqual(rag.questions, ["营服是什么颜色？"])

    def test_does_not_call_rag_when_faq_has_confident_answer(self):
        rag_result = RagSearchResult(
            reply="错误的 RAG 回复",
            source="线下手册",
            confidence=0.99,
            chunks=[],
            is_strong=True,
        )
        rag = FakeRagRetriever(rag_result)

        result = make_engine(rag_retriever=rag).answer("报名入口在哪里？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "registration.link")
        self.assertIn("https://developer.metax-tech.com/activities/18", result.reply)
        self.assertNotIn("v.wjx.cn", result.reply)
        self.assertEqual(rag.questions, [])

    def test_returns_needs_info_when_rag_misses(self):
        result = make_engine(rag_retriever=FakeRagRetriever(None)).answer("营服是什么颜色？")

        self.assertEqual(result.action, "needs_info")
        self.assertIn("当前资料还没有明确说明", result.reply)

    def test_can_use_custom_answer_provider_chain(self):
        result = AnswerEngine(
            KnowledgeBase.from_default(),
            providers=[CustomProvider()],
        ).answer("报名入口在哪里？")

        self.assertEqual(result.action, "suggested_reply")
        self.assertEqual(result.intent, "custom.intent")
        self.assertEqual(result.source, "custom-provider")
        self.assertEqual(result.reply, "自定义回复：报名入口在哪里？")


if __name__ == "__main__":
    unittest.main()
