import unittest

from summer_camp_agent.wechat_compose import ComposeInput, ComposeTarget, WeChatComposeController, WindowsComposeBackend


class FakeComposeBackend:
    def __init__(
        self,
        *,
        target_status="matched",
        input_candidate=None,
        read_after_paste=None,
        title="测试群 - 微信",
    ):
        self.target_status = target_status
        self.input_candidate = input_candidate if input_candidate is not None else ComposeInput(status="found")
        self.read_after_paste = read_after_paste
        self.title = title
        self.clipboard_text = ""
        self.focused = False
        self.shortcuts = []

    def set_clipboard_text(self, text):
        self.clipboard_text = text

    def find_target_window(self, target_group_name, foreground_only=False):
        if self.target_status == "matched":
            return ComposeTarget(status="matched", hwnd=100, title=self.title)
        return ComposeTarget(status=self.target_status, hwnd=0, title="")

    def find_compose_input(self, target):
        return self.input_candidate

    def focus_compose_input(self, target, compose_input):
        if compose_input.status == "found":
            self.focused = True
            return True
        return False

    def send_ctrl_v(self):
        self.shortcuts.append("CTRL+V")

    def read_compose_text(self, compose_input):
        return self.read_after_paste


class WeChatComposeControllerTest(unittest.TestCase):
    def test_copies_without_pasting_when_target_group_is_not_found(self):
        backend = FakeComposeBackend(target_status="not_found")

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertEqual(result.action, "copied")
        self.assertFalse(result.target_found)
        self.assertFalse(result.input_focused)
        self.assertEqual(result.target_status, "not_found")
        self.assertEqual(result.fallback_reason, "target_chat_not_found")
        self.assertEqual(backend.clipboard_text, "同学你好")
        self.assertEqual(backend.shortcuts, [])

    def test_copies_without_pasting_when_input_is_missing(self):
        backend = FakeComposeBackend(input_candidate=ComposeInput(status="not_found"))

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertEqual(result.action, "copied")
        self.assertTrue(result.target_found)
        self.assertFalse(result.input_focused)
        self.assertEqual(result.input_status, "not_found")
        self.assertEqual(result.fallback_reason, "input_not_found")
        self.assertEqual(backend.shortcuts, [])

    def test_does_not_overwrite_existing_input_content(self):
        backend = FakeComposeBackend(input_candidate=ComposeInput(status="found", existing_text="已有内容"))

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertEqual(result.action, "copied")
        self.assertEqual(result.input_status, "not_empty")
        self.assertEqual(result.fallback_reason, "input_not_empty")
        self.assertEqual(backend.shortcuts, [])

    def test_returns_filled_verified_when_readback_matches(self):
        backend = FakeComposeBackend(
            input_candidate=ComposeInput(status="found", existing_text="", can_read=True),
            read_after_paste="同学你好",
        )

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertEqual(result.action, "filled_verified")
        self.assertTrue(result.input_focused)
        self.assertTrue(result.filled)
        self.assertTrue(result.verified)
        self.assertEqual(result.input_status, "focused")
        self.assertEqual(result.verification_status, "matched")
        self.assertEqual(backend.shortcuts, ["CTRL+V"])

    def test_returns_filled_unverified_when_input_text_cannot_be_read(self):
        backend = FakeComposeBackend(input_candidate=ComposeInput(status="found", existing_text=None, can_read=False))

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertEqual(result.action, "filled_unverified")
        self.assertTrue(result.filled)
        self.assertFalse(result.verified)
        self.assertEqual(result.verification_status, "unverified")

    def test_returns_filled_unverified_when_readback_mismatches(self):
        backend = FakeComposeBackend(
            input_candidate=ComposeInput(status="found", existing_text="", can_read=True),
            read_after_paste="别的内容",
        )

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertEqual(result.action, "filled_unverified")
        self.assertTrue(result.filled)
        self.assertFalse(result.verified)
        self.assertEqual(result.verification_status, "mismatch")
        self.assertEqual(result.fallback_reason, "verification_mismatch")


class WindowsComposeBackendTargetSelectionTest(unittest.TestCase):
    def test_foreground_only_target_does_not_activate_matching_background_window(self):
        backend = WindowsComposeBackend.__new__(WindowsComposeBackend)

        target = backend._select_target_window(
            "\u5ba2\u6237\u5f20\u4e09 - \u5fae\u4fe1",
            foreground_hwnd=99,
            foreground_title="Electron",
            wechat_windows=[(10, "\u5ba2\u6237\u5f20\u4e09 - \u5fae\u4fe1")],
            foreground_only=True,
        )

        self.assertEqual(target.status, "not_found")
        self.assertEqual(target.reason, "foreground_wechat_required")

    def test_without_group_target_uses_only_foreground_wechat_window(self):
        backend = WindowsComposeBackend.__new__(WindowsComposeBackend)

        target = backend._select_target_window(
            "",
            foreground_hwnd=10,
            foreground_title="\u5ba2\u6237\u5f20\u4e09 - \u5fae\u4fe1",
            wechat_windows=[(10, "\u5ba2\u6237\u5f20\u4e09 - \u5fae\u4fe1"), (11, "\u5ba2\u6237\u674e\u56db - \u5fae\u4fe1")],
        )

        self.assertEqual(target.status, "matched")
        self.assertEqual(target.hwnd, 10)
        self.assertEqual(target.reason, "foreground_wechat")

    def test_without_group_target_does_not_guess_a_background_wechat_window(self):
        backend = WindowsComposeBackend.__new__(WindowsComposeBackend)

        target = backend._select_target_window(
            "",
            foreground_hwnd=99,
            foreground_title="\u5176\u4ed6\u5e94\u7528",
            wechat_windows=[(10, "\u5ba2\u6237\u5f20\u4e09 - \u5fae\u4fe1")],
        )

        self.assertEqual(target.status, "not_found")
        self.assertEqual(target.reason, "foreground_wechat_required")

    def test_accepts_single_generic_wechat_window_when_group_title_is_not_exposed(self):
        backend = WindowsComposeBackend.__new__(WindowsComposeBackend)

        target = backend._select_target_window(
            "\u6d4b\u8bd5\u5de5\u5177",
            foreground_hwnd=10,
            foreground_title="\u5fae\u4fe1",
            wechat_windows=[(10, "\u5fae\u4fe1")],
        )

        self.assertEqual(target.status, "matched")
        self.assertEqual(target.hwnd, 10)
        self.assertEqual(target.title, "\u5fae\u4fe1")
        self.assertEqual(target.reason, "generic_single_window")

    def test_does_not_guess_when_multiple_generic_wechat_windows_exist(self):
        backend = WindowsComposeBackend.__new__(WindowsComposeBackend)

        target = backend._select_target_window(
            "\u6d4b\u8bd5\u5de5\u5177",
            foreground_hwnd=10,
            foreground_title="\u5fae\u4fe1",
            wechat_windows=[(10, "\u5fae\u4fe1"), (11, "\u5fae\u4fe1")],
        )

        self.assertEqual(target.status, "ambiguous")

    def test_prefers_explicit_group_title_over_generic_window(self):
        backend = WindowsComposeBackend.__new__(WindowsComposeBackend)

        target = backend._select_target_window(
            "\u6d4b\u8bd5\u5de5\u5177",
            foreground_hwnd=10,
            foreground_title="\u5fae\u4fe1",
            wechat_windows=[(10, "\u5fae\u4fe1"), (11, "\u6d4b\u8bd5\u5de5\u5177 - \u5fae\u4fe1")],
        )

        self.assertEqual(target.status, "matched")
        self.assertEqual(target.hwnd, 11)
        self.assertEqual(target.reason, "target_title")


if __name__ == "__main__":
    unittest.main()
