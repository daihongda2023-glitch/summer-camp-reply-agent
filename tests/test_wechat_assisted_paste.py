import ctypes
import inspect
import sys
import unittest

from summer_camp_agent.wechat_assisted_paste import AssistedPasteAdapter, PasteResult, WindowsPasteBackend


class FakeBackend:
    def __init__(self, can_paste=True):
        self.can_paste = can_paste
        self.clipboard_text = ""
        self.shortcuts = []

    def set_clipboard_text(self, text):
        self.clipboard_text = text

    def foreground_window_title(self):
        return "微信"

    def send_ctrl_v(self):
        if not self.can_paste:
            raise OSError("paste failed")
        self.shortcuts.append("CTRL+V")


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

    def test_module_does_not_send_enter_or_mouse_clicks(self):
        import summer_camp_agent.wechat_assisted_paste as module

        source = inspect.getsource(module).lower()

        self.assertNotIn("vk_return", source)
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


class WechatCheckedPasteTest(unittest.TestCase):
    def test_checked_paste_downgrades_when_foreground_is_not_wechat(self):
        backend = NonWechatBackend()

        result = AssistedPasteAdapter(backend).paste_to_wechat_foreground("同学你好")

        self.assertEqual(result.action, "copied")
        self.assertEqual(backend.clipboard_text, "同学你好")
        self.assertEqual(backend.shortcuts, [])
        self.assertIn("请切回微信", result.message)

    def test_checked_paste_allows_wechat_foreground(self):
        backend = FakeBackend()

        result = AssistedPasteAdapter(backend).paste_to_wechat_foreground("同学你好")

        self.assertEqual(result.action, "pasted")
        self.assertEqual(backend.shortcuts, ["CTRL+V"])


if __name__ == "__main__":
    unittest.main()
