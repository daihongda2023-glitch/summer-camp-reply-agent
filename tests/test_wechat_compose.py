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
        requires_focus_wait=False,
        focus_wait_result=True,
        requires_prepare=False,
    ):
        self.target_status = target_status
        self.input_candidate = input_candidate if input_candidate is not None else ComposeInput(status="found")
        self.read_after_paste = read_after_paste
        self.title = title
        self.clipboard_text = ""
        self.focused = False
        self.shortcuts = []
        self.requires_focus_wait = requires_focus_wait
        self.focus_wait_result = focus_wait_result
        self.focus_waited = False
        self.requires_prepare = requires_prepare
        self.prepared = False

    def set_clipboard_text(self, text):
        self.clipboard_text = text

    def find_target_window(self, target_group_name):
        if self.target_status == "matched":
            return ComposeTarget(status="matched", hwnd=100, title=self.title)
        return ComposeTarget(status=self.target_status, hwnd=0, title="")

    def find_compose_input(self, target):
        if self.requires_prepare and not self.prepared:
            return ComposeInput(status="not_found")
        return self.input_candidate

    def prepare_target_window(self, target):
        self.prepared = True
        return True

    def focus_compose_input(self, target, compose_input):
        if compose_input.status == "found":
            self.focused = True
            return True
        return False

    def send_ctrl_v(self):
        if self.requires_focus_wait and not self.focus_waited:
            raise OSError("paste sent before focus stabilized")
        self.shortcuts.append("CTRL+V")

    def wait_until_target_focused(self, target):
        self.focus_waited = True
        return self.focus_wait_result

    def read_compose_text(self, compose_input):
        return self.read_after_paste


class WeChatComposeControllerTest(unittest.TestCase):
    def test_prepares_minimized_wechat_window_before_locating_input(self):
        backend = FakeComposeBackend(
            input_candidate=ComposeInput(status="found", existing_text=None, can_read=False),
            requires_prepare=True,
        )

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertTrue(backend.prepared)
        self.assertEqual(result.action, "filled_unverified")
        self.assertEqual(backend.shortcuts, ["CTRL+V"])

    def test_waits_for_wechat_focus_before_sending_ctrl_v(self):
        backend = FakeComposeBackend(
            input_candidate=ComposeInput(status="found", existing_text=None, can_read=False),
            requires_focus_wait=True,
        )

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertEqual(result.action, "filled_unverified")
        self.assertTrue(backend.focus_waited)
        self.assertEqual(backend.shortcuts, ["CTRL+V"])

    def test_keeps_clipboard_fallback_when_wechat_focus_never_stabilizes(self):
        backend = FakeComposeBackend(
            input_candidate=ComposeInput(status="found", existing_text=None, can_read=False),
            focus_wait_result=False,
        )

        result = WeChatComposeController(backend).fill_reply("同学你好", target_group_name="测试群")

        self.assertEqual(result.action, "copied")
        self.assertEqual(result.fallback_reason, "focus_not_confirmed")
        self.assertEqual(result.input_status, "focus_pending")
        self.assertEqual(backend.shortcuts, [])

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
    def test_minimized_wechat_window_remains_a_candidate_for_restore(self):
        class FakeUser32:
            @staticmethod
            def IsWindowVisible(hwnd):
                return True

            @staticmethod
            def IsIconic(hwnd):
                return True

        backend = WindowsComposeBackend.__new__(WindowsComposeBackend)
        backend.user32 = FakeUser32()
        backend.window_rect = lambda hwnd: (-32000, -32000, -31763, -31961)

        self.assertTrue(backend.is_usable_window(100, "微信"))

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
