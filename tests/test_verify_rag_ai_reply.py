import unittest

from scripts.verify_rag_ai_reply import (
    build_verification_wechat_config,
    collect_verification_items,
    is_completed_auto_send,
)


class VerifyRagAIReplyScriptTest(unittest.TestCase):
    def test_real_ai_smoke_uses_auto_send_without_debug_review(self):
        config = build_verification_wechat_config()

        self.assertEqual(config["send_mode"], "auto_send")
        self.assertFalse(config["debug_review_mode"])

    def test_real_ai_smoke_reads_completed_auto_send_history(self):
        class FakeState:
            def __init__(self):
                self.scopes = []

            def list_items(self, *, scope):
                self.scopes.append(scope)
                return {"items": [{"status": "已发送"}]}

        state = FakeState()

        items = collect_verification_items(state)

        self.assertEqual(items, [{"status": "已发送"}])
        self.assertEqual(state.scopes, ["all"])

    def test_real_ai_smoke_accepts_current_sent_history_status(self):
        self.assertTrue(
            is_completed_auto_send(
                {"status": "已发送", "mode": "auto_send"}
            )
        )
        self.assertFalse(
            is_completed_auto_send(
                {"status": "已回复", "mode": "auto_send"}
            )
        )


if __name__ == "__main__":
    unittest.main()
