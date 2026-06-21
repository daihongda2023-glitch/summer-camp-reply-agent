import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.desktop_chat import DesktopChatSession
from summer_camp_agent.gui import SummerCampAgentApp


class DesktopChatSessionTest(unittest.TestCase):
    def test_gui_app_class_is_importable(self):
        self.assertEqual(SummerCampAgentApp.__name__, "SummerCampAgentApp")

    def test_reply_message_contains_recommendation_and_answer(self):
        session = DesktopChatSession()

        message = session.ask("报名入口在哪里？")

        self.assertEqual(message.recommendation, "send")
        self.assertIn("建议动作：send", message.display_text)
        self.assertIn("当前资料中的报名入口为", message.display_text)

    def test_unknown_question_can_be_saved_as_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "pending.jsonl"
            session = DesktopChatSession(pending_log_path=pending_path)
            message = session.ask("营服是什么颜色？")

            saved = session.save_last_pending()

            self.assertTrue(saved)
            self.assertEqual(message.recommendation, "mark_pending")
            self.assertIn("营服是什么颜色", pending_path.read_text(encoding="utf-8"))

    def test_save_pending_returns_false_when_last_message_is_not_pending(self):
        session = DesktopChatSession()
        session.ask("报名入口在哪里？")

        self.assertFalse(session.save_last_pending())


if __name__ == "__main__":
    unittest.main()
