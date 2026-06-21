import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.desktop_chat import DesktopChatSession
from summer_camp_agent.knowledge import KnowledgeBase


class DesktopCorrectionTest(unittest.TestCase):
    def test_correction_command_teaches_previous_question(self):
        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "local_overrides.json"
            session = DesktopChatSession(override_path=override_path)

            first = session.ask("营服是什么颜色？")
            correction = session.ask("修正上个问题的回答结果：营服是深蓝色，现场报到时发放。")
            second = session.ask("营服是什么颜色？")

            self.assertEqual(first.recommendation, "mark_pending")
            self.assertEqual(correction.recommendation, "saved_correction")
            self.assertIn("已保存修正", correction.display_text)
            self.assertEqual(second.recommendation, "send")
            self.assertIn("营服是深蓝色", second.display_text)

    def test_correction_persists_across_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "local_overrides.json"
            session = DesktopChatSession(override_path=override_path)
            session.ask("营服是什么颜色？")
            session.ask("修正上个问题的回答结果：营服是深蓝色，现场报到时发放。")

            new_session = DesktopChatSession(override_path=override_path)
            message = new_session.ask("营服是什么颜色？")

            self.assertEqual(message.recommendation, "send")
            self.assertIn("桌面验证修正", message.display_text)
            self.assertIn("营服是深蓝色", message.display_text)

    def test_correction_without_previous_question_does_not_write_override(self):
        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "local_overrides.json"
            session = DesktopChatSession(override_path=override_path)

            message = session.ask("修正上个问题的回答结果：营服是深蓝色。")

            self.assertEqual(message.recommendation, "needs_previous_question")
            self.assertIn("还没有可修正的上一个问题", message.display_text)
            self.assertFalse(override_path.exists())

    def test_knowledge_base_loads_overrides_before_default_faq(self):
        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "local_overrides.json"
            session = DesktopChatSession(override_path=override_path)
            session.ask("报名入口在哪里？")
            session.ask("修正上个问题的回答结果：请以最新群公告中的报名入口为准。")

            kb = KnowledgeBase.from_default(override_path=override_path)

            self.assertEqual(kb.items[0].source, "桌面验证修正")
            self.assertEqual(kb.items[0].question, "报名入口在哪里？")


if __name__ == "__main__":
    unittest.main()
