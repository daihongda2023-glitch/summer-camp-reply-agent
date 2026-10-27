import unittest

from summer_camp_agent.answer_providers import AnswerProviderChain, ProviderAnswer
from summer_camp_agent.engine import AnswerResult


class MissProvider:
    name = "miss"

    def answer(self, text: str) -> ProviderAnswer:
        return ProviderAnswer.miss(reason="not matched")


class HitProvider:
    name = "hit"

    def answer(self, text: str) -> ProviderAnswer:
        return ProviderAnswer.hit(
            AnswerResult(
                action="auto_reply",
                reply=f"命中：{text}",
                intent="test.hit",
                source="fake",
                confidence=0.9,
            )
        )


class AnswerProviderChainTest(unittest.TestCase):
    def test_uses_first_provider_that_returns_answer(self):
        chain = AnswerProviderChain([MissProvider(), HitProvider()])

        result = chain.answer("报名入口在哪")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "test.hit")
        self.assertEqual(result.reply, "命中：报名入口在哪")

    def test_returns_default_when_all_providers_miss(self):
        chain = AnswerProviderChain([MissProvider()])

        result = chain.answer("未知问题")

        self.assertEqual(result.action, "needs_info")
        self.assertEqual(result.reason, "unknown")


if __name__ == "__main__":
    unittest.main()
