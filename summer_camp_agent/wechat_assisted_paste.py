from __future__ import annotations

import ctypes
from dataclasses import dataclass
import sys


@dataclass(frozen=True)
class PasteResult:
    action: str
    message: str
    foreground_window_title: str = ""


class AssistedPasteAdapter:
    def __init__(self, backend=None):
        self.backend = backend or WindowsPasteBackend()

    def copy_only(self, text: str) -> PasteResult:
        value = text.strip()
        if not value:
            return PasteResult("failed", "回复内容不能为空。")
        try:
            self.backend.set_clipboard_text(value)
        except Exception as exc:  # noqa: BLE001
            return PasteResult("failed", f"写入剪贴板失败：{exc}")
        return PasteResult("copied", "已复制到剪贴板，请手动粘贴到微信输入框。")

    def paste_to_foreground(self, text: str) -> PasteResult:
        copied = self.copy_only(text)
        if copied.action != "copied":
            return copied
        title = ""
        try:
            title = self.backend.foreground_window_title()
            self.backend.send_ctrl_v()
            return PasteResult("pasted", "已填入当前前台窗口，请在微信中确认后手动发送。", title)
        except Exception:
            return PasteResult("copied", "已复制到剪贴板，但未能自动粘贴。请手动粘贴到微信输入框。", title)


class WindowsPasteBackend:
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_V = 0x56

    def __init__(self):
        self.user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        self.kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

    def set_clipboard_text(self, text: str) -> None:
        if sys.platform != "win32":
            raise OSError("当前平台不支持自动写入系统剪贴板")
        data = (text + "\0").encode("utf-16le")
        h_global = self.kernel32.GlobalAlloc(self.GMEM_MOVEABLE, len(data))
        if not h_global:
            raise OSError("GlobalAlloc failed")
        locked = self.kernel32.GlobalLock(h_global)
        if not locked:
            raise OSError("GlobalLock failed")
        ctypes.memmove(locked, data, len(data))
        self.kernel32.GlobalUnlock(h_global)
        if not self.user32.OpenClipboard(None):
            raise OSError("OpenClipboard failed")
        try:
            self.user32.EmptyClipboard()
            if not self.user32.SetClipboardData(self.CF_UNICODETEXT, h_global):
                raise OSError("SetClipboardData failed")
        finally:
            self.user32.CloseClipboard()

    def foreground_window_title(self) -> str:
        if sys.platform != "win32":
            return ""
        hwnd = self.user32.GetForegroundWindow()
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def send_ctrl_v(self) -> None:
        if sys.platform != "win32":
            raise OSError("当前平台不支持自动粘贴")
        self._key_down(self.VK_CONTROL)
        self._key_down(self.VK_V)
        self._key_up(self.VK_V)
        self._key_up(self.VK_CONTROL)

    def _key_down(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, 0, 0)

    def _key_up(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, self.KEYEVENTF_KEYUP, 0)
