from __future__ import annotations

import ctypes
import ctypes.wintypes
from dataclasses import dataclass
import sys
import time

from .wechat_compose import ComposeFillResult, WeChatComposeController, WindowsComposeBackend


@dataclass(frozen=True)
class PasteResult:
    action: str
    message: str
    foreground_window_title: str = ""
    target_found: bool = False
    input_focused: bool = False
    filled: bool = False
    verified: bool = False
    fallback_reason: str = ""
    target_status: str = "unknown"
    input_status: str = "unknown"
    verification_status: str = "unverified"


class AssistedPasteAdapter:
    def __init__(self, backend=None):
        self.backend = backend or WindowsPasteBackend()
        compose_backend = self.backend if hasattr(self.backend, "find_target_window") else WindowsComposeBackend(self.backend)
        self.compose_controller = WeChatComposeController(compose_backend)

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

    def paste_to_wechat_foreground(self, text: str, target_group_name: str = "") -> PasteResult:
        return self._from_compose_result(
            self.compose_controller.fill_reply(text, target_group_name=target_group_name)
        )

    def send_to_wechat_foreground(self, text: str, target_group_name: str = "") -> PasteResult:
        fill_result = self.compose_controller.fill_reply(text, target_group_name=target_group_name)
        pasted = self._from_compose_result(fill_result)
        if not self._can_auto_send_after_fill(pasted):
            return pasted

        try:
            time.sleep(0.15)
            self.compose_controller.backend.send_enter()
        except Exception as exc:  # noqa: BLE001
            return PasteResult(
                pasted.action,
                f"已填入微信输入框，但自动发布失败：{exc}",
                pasted.foreground_window_title,
                target_found=pasted.target_found,
                input_focused=pasted.input_focused,
                filled=pasted.filled,
                verified=pasted.verified,
                fallback_reason="send_failed",
                target_status=pasted.target_status,
                input_status=pasted.input_status,
                verification_status=pasted.verification_status,
            )

        return PasteResult(
            "sent_verified" if pasted.verified else "sent_unverified",
            "已自动发布到微信。" if pasted.verified else "已填入但无法自动校验，已按配置自动发布到微信。",
            pasted.foreground_window_title,
            target_found=pasted.target_found,
            input_focused=pasted.input_focused,
            filled=pasted.filled,
            verified=pasted.verified,
            target_status=pasted.target_status,
            input_status=pasted.input_status,
            verification_status=pasted.verification_status,
        )

    def _can_auto_send_after_fill(self, result: PasteResult) -> bool:
        if not result.filled or not result.input_focused:
            return False
        return result.verification_status in {"matched", "unverified"}

    def _from_compose_result(self, result: ComposeFillResult) -> PasteResult:
        return PasteResult(
            result.action,
            result.message,
            result.foreground_window_title,
            target_found=result.target_found,
            input_focused=result.input_focused,
            filled=result.filled,
            verified=result.verified,
            fallback_reason=result.fallback_reason,
            target_status=result.target_status,
            input_status=result.input_status,
            verification_status=result.verification_status,
        )


class WindowsPasteBackend:
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_V = 0x56
    VK_RETURN = 0x0D

    def __init__(self):
        self.user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        self.kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None
        if sys.platform == "win32":
            self._configure_win32_api()

    def _configure_win32_api(self) -> None:
        self.kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        self.kernel32.GlobalAlloc.restype = ctypes.c_void_p
        self.kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalLock.restype = ctypes.c_void_p
        self.kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
        self.kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalFree.restype = ctypes.c_void_p
        self.user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
        self.user32.OpenClipboard.restype = ctypes.wintypes.BOOL
        self.user32.EmptyClipboard.argtypes = []
        self.user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
        self.user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        self.user32.SetClipboardData.restype = ctypes.c_void_p
        self.user32.CloseClipboard.argtypes = []
        self.user32.CloseClipboard.restype = ctypes.wintypes.BOOL
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        self.user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.wintypes.DWORD, ctypes.c_void_p]
        self.user32.keybd_event.restype = None

    def set_clipboard_text(self, text: str) -> None:
        if sys.platform != "win32":
            raise OSError("当前平台不支持自动写入系统剪贴板")
        data = (text + "\0").encode("utf-16le")
        h_global = self.kernel32.GlobalAlloc(self.GMEM_MOVEABLE, len(data))
        if not h_global:
            raise OSError("GlobalAlloc failed")
        locked = self.kernel32.GlobalLock(h_global)
        if not locked:
            self.kernel32.GlobalFree(h_global)
            raise OSError("GlobalLock failed")
        ctypes.memmove(locked, data, len(data))
        self.kernel32.GlobalUnlock(h_global)
        if not self.user32.OpenClipboard(None):
            self.kernel32.GlobalFree(h_global)
            raise OSError("OpenClipboard failed")
        try:
            self.user32.EmptyClipboard()
            if not self.user32.SetClipboardData(self.CF_UNICODETEXT, h_global):
                self.kernel32.GlobalFree(h_global)
                raise OSError("SetClipboardData failed")
            h_global = None
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

    def send_enter(self) -> None:
        if sys.platform != "win32":
            raise OSError("当前平台不支持自动发送")
        self._key_down(self.VK_RETURN)
        self._key_up(self.VK_RETURN)

    def _key_down(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, 0, 0)

    def _key_up(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, self.KEYEVENTF_KEYUP, 0)
