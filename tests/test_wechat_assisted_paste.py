import ctypes
import inspect
import sys
import unittest

from summer_camp_agent.wechat_assisted_paste import AssistedPasteAdapter, PasteResult, WindowsPasteBackend
from summer_camp_agent.wechat_compose import ComposeInput, ComposeTarget


class FakeBackend:
    def __init__(self, can_paste=True, target_status="matched", input_candidate=None, read_after_paste="同学你好"):
        self.can_paste = can_paste
        self.target_status = target_status
        self.input_candidate = input_candidate if input_candidate is not None else ComposeInput(status="found", existing_text="", can_read=True)
        self.read_after_paste = read_after_paste
        self.clipboard_text = ""
        self.shortcuts = []
        self.focused = False

    def set_clipboard_text(self, text):
        self.clipboard_text = text

    def foreground_window_title(self):
        return "微信"

    def find_target_window(self, target_group_name):
        if self.target_status == "matched":
            return ComposeTarget(status="matched", hwnd=100, title="微信")
        return ComposeTarget(status=self.target_status, hwnd=0, title="")

    def find_compose_input(self, target):
        return self.input_candidate

    def focus_compose_input(self, target, compose_input):
        if compose_input.status == "found":
            self.focused = True
            return True
        return False

    def send_ctrl_v(self):
        if not self.can_paste:
            raise OSError("paste failed")
        self.shortcuts.append("CTRL+V")

    def send_enter(self):
        if not self.can_paste:
            raise OSError("send failed")
        self.shortcuts.append("ENTER")

    def read_compose_text(self, compose_input):
        return self.read_after_paste


class WechatAssistedPasteTest(unittest.TestCase):
    def test_copy_only_rejects_empty_text(self):
        result = AssistedPasteAdapter(FakeBackend()).copy_only("   ")

        self.assertEqual(result.action, "failed")
        self.assertIn("不能为空", result.message)

    def test_copy_only_writes_clipboard_without_paste(self):
        backend = FakeBackend()

        result = AssistedPasteAdapter(backend).copy_only("同学你好")

        self.assertEqual(result.action, "copied")
        self.assertEqual(backend.clipboard_text, "同学你好")
        self.assertEqual(backend.shortcuts, [])

    def test_paste_to_foreground_uses_only_ctrl_v(self):
        backend = FakeBackend()

        result = AssistedPasteAdapter(backend).paste_to_foreground("同学你好")

        self.assertEqual(result.action, "pasted")
        self.assertEqual(backend.shortcuts, ["CTRL+V"])
        self.assertEqual(result.foreground_window_title, "微信")

    def test_paste_failure_downgrades_to_copied(self):
        backend = FakeBackend(can_paste=False)

        result = AssistedPasteAdapter(backend).paste_to_foreground("同学你好")

        self.assertEqual(result.action, "copied")
        self.assertIn("已复制到剪贴板", result.message)

    def test_module_does_not_use_mouse_clicks(self):
        import summer_camp_agent.wechat_assisted_paste as module

        source = inspect.getsource(module).lower()

        self.assertNotIn("mouseevent", source)
        self.assertNotIn("leftdown", source)
        self.assertNotIn("leftup", source)
        self.assertIsInstance(PasteResult("copied", "ok"), PasteResult)

    @unittest.skipUnless(sys.platform == "win32", "Windows API signatures only apply on Windows")
    def test_windows_backend_declares_pointer_sized_clipboard_handles(self):
        backend = WindowsPasteBackend()

        self.assertIs(backend.kernel32.GlobalAlloc.restype, ctypes.c_void_p)
        self.assertIs(backend.kernel32.GlobalLock.restype, ctypes.c_void_p)
        self.assertIs(backend.kernel32.GlobalFree.restype, ctypes.c_void_p)
        self.assertIs(backend.user32.SetClipboardData.restype, ctypes.c_void_p)
        self.assertEqual(backend.kernel32.GlobalLock.argtypes, [ctypes.c_void_p])
        self.assertEqual(backend.user32.SetClipboardData.argtypes, [ctypes.c_uint, ctypes.c_void_p])


class NonWechatBackend(FakeBackend):
    def foreground_window_title(self):
        return "Visual Studio Code"

    def find_target_window(self, target_group_name):
        return ComposeTarget(status="not_found", hwnd=0, title="")


class WechatCheckedPasteTest(unittest.TestCase):
    def test_checked_paste_downgrades_when_foreground_is_not_wechat(self):
        backend = NonWechatBackend()

        result = AssistedPasteAdapter(backend).paste_to_wechat_foreground("同学你好")

        self.assertEqual(result.action, "copied")
        self.assertEqual(backend.clipboard_text, "同学你好")
        self.assertEqual(backend.shortcuts, [])
        self.assertEqual(result.target_status, "not_found")
        self.assertEqual(result.fallback_reason, "target_chat_not_found")
        self.assertIn("未找到目标微信群", result.message)

    def test_checked_paste_allows_wechat_foreground(self):
        backend = FakeBackend()

        result = AssistedPasteAdapter(backend).paste_to_wechat_foreground("同学你好")

        self.assertEqual(result.action, "filled_verified")
        self.assertEqual(backend.shortcuts, ["CTRL+V"])

    def test_checked_auto_send_never_presses_enter_for_wechat_foreground(self):
        backend = FakeBackend()

        result = AssistedPasteAdapter(backend).send_to_wechat_foreground("同学你好")

        self.assertEqual(result.action, "filled_verified")
        self.assertEqual(backend.shortcuts, ["CTRL+V"])

    def test_checked_auto_send_downgrades_when_foreground_is_not_wechat(self):
        backend = NonWechatBackend()

        result = AssistedPasteAdapter(backend).send_to_wechat_foreground("同学你好")

        self.assertEqual(result.action, "copied")
        self.assertEqual(backend.shortcuts, [])


if __name__ == "__main__":
    unittest.main()
