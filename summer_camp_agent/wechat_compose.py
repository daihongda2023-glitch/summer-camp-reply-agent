from __future__ import annotations

import ctypes
import ctypes.wintypes
from dataclasses import dataclass
import sys
from typing import Callable

from .wechat_window import enable_process_dpi_awareness, is_wechat_window_title


@dataclass(frozen=True)
class ComposeTarget:
    status: str
    hwnd: int = 0
    title: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ComposeInput:
    status: str
    hwnd: int = 0
    rect: tuple[int, int, int, int] | None = None
    existing_text: str | None = None
    can_read: bool = False
    method: str = ""


@dataclass(frozen=True)
class ComposeFillResult:
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


class WeChatComposeController:
    def __init__(self, backend):
        self.backend = backend

    def fill_reply(self, text: str, *, target_group_name: str = "") -> ComposeFillResult:
        value = text.strip()
        if not value:
            return ComposeFillResult("failed", "回复内容不能为空。", fallback_reason="empty_reply")

        try:
            self.backend.set_clipboard_text(value)
        except Exception as exc:  # noqa: BLE001
            return ComposeFillResult("failed", f"写入剪贴板失败：{exc}", fallback_reason="clipboard_failed")

        target = self.backend.find_target_window(target_group_name)
        if target.status != "matched":
            return self._target_failure(target)

        compose_input = self.backend.find_compose_input(target)
        if compose_input.status != "found":
            return ComposeFillResult(
                "copied",
                "未找到微信输入框，已复制到剪贴板。请手动粘贴到目标群输入框。",
                foreground_window_title=target.title,
                target_found=True,
                fallback_reason="input_not_found",
                target_status=target.status,
                input_status="not_found",
            )

        existing = compose_input.existing_text
        if existing is not None and existing.strip():
            return ComposeFillResult(
                "copied",
                "输入框已有内容，未覆盖；回复已复制到剪贴板。",
                foreground_window_title=target.title,
                target_found=True,
                fallback_reason="input_not_empty",
                target_status=target.status,
                input_status="not_empty",
            )

        if not self.backend.focus_compose_input(target, compose_input):
            return ComposeFillResult(
                "copied",
                "未能聚焦微信输入框，已复制到剪贴板。请手动粘贴。",
                foreground_window_title=target.title,
                target_found=True,
                fallback_reason="input_not_found",
                target_status=target.status,
                input_status="not_found",
            )

        try:
            self.backend.send_ctrl_v()
        except Exception as exc:  # noqa: BLE001
            return ComposeFillResult(
                "failed",
                f"填入微信输入框失败：{exc}",
                foreground_window_title=target.title,
                target_found=True,
                input_focused=True,
                fallback_reason="fill_failed",
                target_status=target.status,
                input_status="focused",
            )

        return self._verify_fill(value, target, compose_input)

    def _target_failure(self, target: ComposeTarget) -> ComposeFillResult:
        if target.status == "ambiguous":
            message = "找到多个匹配微信窗口，已复制到剪贴板。请切到目标群后手动粘贴。"
            reason = "target_chat_ambiguous"
        else:
            message = "未找到目标微信群，已复制到剪贴板。请切到目标群后手动粘贴。"
            reason = "target_chat_not_found"
        return ComposeFillResult(
            "copied",
            message,
            foreground_window_title=target.title,
            fallback_reason=reason,
            target_status=target.status,
        )

    def _verify_fill(self, value: str, target: ComposeTarget, compose_input: ComposeInput) -> ComposeFillResult:
        readback = self.backend.read_compose_text(compose_input)
        if readback is None:
            return ComposeFillResult(
                "filled_unverified",
                "已填入但无法自动校验，请人工检查后手动发送。",
                foreground_window_title=target.title,
                target_found=True,
                input_focused=True,
                filled=True,
                target_status=target.status,
                input_status="focused",
                verification_status="unverified",
            )
        if value in readback:
            return ComposeFillResult(
                "filled_verified",
                "已填入并校验，请在微信中检查后手动发送。",
                foreground_window_title=target.title,
                target_found=True,
                input_focused=True,
                filled=True,
                verified=True,
                target_status=target.status,
                input_status="focused",
                verification_status="matched",
            )
        return ComposeFillResult(
            "filled_unverified",
            "已填入但校验未通过，请人工检查后手动发送。",
            foreground_window_title=target.title,
            target_found=True,
            input_focused=True,
            filled=True,
            fallback_reason="verification_mismatch",
            target_status=target.status,
            input_status="focused",
            verification_status="mismatch",
        )


class WindowsComposeBackend:
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_V = 0x56
    VK_RETURN = 0x0D
    WM_GETTEXT = 0x000D
    WM_GETTEXTLENGTH = 0x000E
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004

    def __init__(self, clipboard_backend=None):
        self.clipboard_backend = clipboard_backend
        self.user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        if sys.platform == "win32":
            enable_process_dpi_awareness()
            self._configure_win32_api()

    def _configure_win32_api(self) -> None:
        self.user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.user32.EnumWindows.restype = ctypes.wintypes.BOOL
        self.user32.EnumChildWindows.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p]
        self.user32.EnumChildWindows.restype = ctypes.wintypes.BOOL
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        self.user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetClassNameW.restype = ctypes.c_int
        self.user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
        self.user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
        self.user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
        self.user32.GetWindowRect.restype = ctypes.wintypes.BOOL
        self.user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
        self.user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL
        self.user32.SetFocus.argtypes = [ctypes.wintypes.HWND]
        self.user32.SetFocus.restype = ctypes.wintypes.HWND
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = ctypes.wintypes.BOOL
        self.user32.mouse_event.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self.user32.mouse_event.restype = None
        self.user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.wintypes.DWORD, ctypes.c_void_p]
        self.user32.keybd_event.restype = None
        self.user32.SendMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
        self.user32.SendMessageW.restype = ctypes.wintypes.LPARAM

    def set_clipboard_text(self, text: str) -> None:
        if self.clipboard_backend is None:
            raise OSError("当前平台不支持自动写入系统剪贴板")
        self.clipboard_backend.set_clipboard_text(text)

    def find_target_window(self, target_group_name: str) -> ComposeTarget:
        if sys.platform != "win32":
            return ComposeTarget("not_found", reason="unsupported_platform")

        target_name = target_group_name.strip()
        foreground_hwnd = int(self.user32.GetForegroundWindow() or 0)
        foreground_title = self.window_title(foreground_hwnd)
        wechat_windows: list[tuple[int, str]] = []

        def collect(hwnd: int) -> bool:
            title = self.window_title(hwnd)
            if self.is_usable_window(hwnd, title):
                wechat_windows.append((hwnd, title))
            return True

        self.enum_windows(collect)
        return self._select_target_window(
            target_name,
            foreground_hwnd=foreground_hwnd,
            foreground_title=foreground_title,
            wechat_windows=wechat_windows,
        )

    def find_compose_input(self, target: ComposeTarget) -> ComposeInput:
        if sys.platform != "win32" or not target.hwnd:
            return ComposeInput("not_found")
        child = self._find_child_edit(target.hwnd)
        if child is not None:
            return child
        fallback = self._fallback_input_rect(target.hwnd)
        if fallback is not None:
            return fallback
        return ComposeInput("not_found")

    def focus_compose_input(self, target: ComposeTarget, compose_input: ComposeInput) -> bool:
        if sys.platform != "win32" or not target.hwnd:
            return False
        self.user32.SetForegroundWindow(target.hwnd)
        if compose_input.hwnd:
            self.user32.SetFocus(compose_input.hwnd)
        if compose_input.rect:
            self._click_rect_center(compose_input.rect)
        return True

    def send_ctrl_v(self) -> None:
        if self.clipboard_backend is not None and hasattr(self.clipboard_backend, "send_ctrl_v"):
            self.clipboard_backend.send_ctrl_v()
            return
        if sys.platform != "win32":
            raise OSError("当前平台不支持自动粘贴")
        self._key_down(self.VK_CONTROL)
        self._key_down(self.VK_V)
        self._key_up(self.VK_V)
        self._key_up(self.VK_CONTROL)

    def send_enter(self) -> None:
        if self.clipboard_backend is not None and hasattr(self.clipboard_backend, "send_enter"):
            self.clipboard_backend.send_enter()
            return
        if sys.platform != "win32":
            raise OSError("当前平台不支持自动发送")
        self._key_down(self.VK_RETURN)
        self._key_up(self.VK_RETURN)

    def read_compose_text(self, compose_input: ComposeInput) -> str | None:
        if sys.platform != "win32" or not compose_input.hwnd or not compose_input.can_read:
            return None
        return self._window_text_by_message(compose_input.hwnd)

    def enum_windows(self, visitor: Callable[[int], bool]) -> None:
        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            return bool(visitor(int(hwnd)))

        self.user32.EnumWindows(enum_proc_type(callback), 0)

    def enum_child_windows(self, parent_hwnd: int, visitor: Callable[[int], bool]) -> None:
        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            return bool(visitor(int(hwnd)))

        self.user32.EnumChildWindows(parent_hwnd, enum_proc_type(callback), 0)

    def is_usable_window(self, hwnd: int, title: str) -> bool:
        if not hwnd or not is_wechat_window_title(title):
            return False
        if not self.user32.IsWindowVisible(hwnd):
            return False
        left, top, right, bottom = self.window_rect(hwnd)
        return (right - left) >= 240 and (bottom - top) >= 240

    def window_title(self, hwnd: int) -> str:
        if not hwnd:
            return ""
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def class_name(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = ctypes.wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return 0, 0, 0, 0
        return rect.left, rect.top, rect.right, rect.bottom

    def _find_child_edit(self, target_hwnd: int) -> ComposeInput | None:
        parent_rect = self.window_rect(target_hwnd)
        _, parent_top, _, parent_bottom = parent_rect
        candidates: list[ComposeInput] = []

        def collect(hwnd: int) -> bool:
            class_name = self.class_name(hwnd).lower()
            if "edit" not in class_name:
                return True
            if not self.user32.IsWindowVisible(hwnd):
                return True
            rect = self.window_rect(hwnd)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            if width < 120 or height < 20:
                return True
            if top < parent_top + int((parent_bottom - parent_top) * 0.45):
                return True
            candidates.append(
                ComposeInput(
                    status="found",
                    hwnd=hwnd,
                    rect=rect,
                    existing_text=self._window_text_by_message(hwnd),
                    can_read=True,
                    method="win32_child_edit",
                )
            )
            return True

        self.enum_child_windows(target_hwnd, collect)
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: self._rect_area(item.rect), reverse=True)[0]

    def _fallback_input_rect(self, target_hwnd: int) -> ComposeInput | None:
        left, top, right, bottom = self.window_rect(target_hwnd)
        width = right - left
        height = bottom - top
        if width < 240 or height < 240:
            return None
        input_top = bottom - max(88, int(height * 0.24))
        input_bottom = bottom - 18
        input_left = left + 18
        input_right = right - max(110, int(width * 0.18))
        if input_right - input_left < 120 or input_bottom - input_top < 36:
            return None
        return ComposeInput(
            status="found",
            rect=(input_left, input_top, input_right, input_bottom),
            existing_text=None,
            can_read=False,
            method="safe_bottom_rect",
        )

    def _window_text_by_message(self, hwnd: int) -> str:
        length = int(self.user32.SendMessageW(hwnd, self.WM_GETTEXTLENGTH, 0, 0))
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.SendMessageW(hwnd, self.WM_GETTEXT, length + 1, ctypes.addressof(buffer))
        return buffer.value

    def _click_rect_center(self, rect: tuple[int, int, int, int]) -> None:
        left, top, right, bottom = rect
        x = left + (right - left) // 2
        y = top + (bottom - top) // 2
        self.user32.SetCursorPos(x, y)
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, None)

    def _key_down(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, 0, 0)

    def _key_up(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, self.KEYEVENTF_KEYUP, 0)

    def _matches_target_title(self, title: str, target_group_name: str) -> bool:
        if not is_wechat_window_title(title):
            return False
        if not target_group_name:
            return True
        return title == target_group_name or title == f"{target_group_name} - 微信" or target_group_name in title

    def _select_target_window(
        self,
        target_group_name: str,
        *,
        foreground_hwnd: int,
        foreground_title: str,
        wechat_windows: list[tuple[int, str]],
    ) -> ComposeTarget:
        unique = self._dedupe_windows(wechat_windows)
        target_matches = [(hwnd, title) for hwnd, title in unique if self._matches_target_title(title, target_group_name)]

        for hwnd, title in target_matches:
            if hwnd == foreground_hwnd:
                return ComposeTarget("matched", hwnd, title, reason="target_title")

        if len(target_matches) == 1:
            hwnd, title = target_matches[0]
            return ComposeTarget("matched", hwnd, title, reason="target_title")
        if len(target_matches) > 1:
            return ComposeTarget("ambiguous", title=", ".join(title for _, title in target_matches[:3]), reason="target_title")

        if target_group_name and len(unique) == 1:
            hwnd, title = unique[0]
            if self._is_generic_wechat_title(title):
                return ComposeTarget("matched", hwnd, title, reason="generic_single_window")

        if target_group_name and len(unique) > 1:
            return ComposeTarget("ambiguous", title=", ".join(title for _, title in unique[:3]), reason="wechat_window_ambiguous")

        return ComposeTarget("not_found", title=foreground_title, reason="target_title_not_found")

    def _is_generic_wechat_title(self, title: str) -> bool:
        return title.strip() == "微信"

    def _dedupe_windows(self, windows: list[tuple[int, str]]) -> list[tuple[int, str]]:
        seen: set[int] = set()
        unique: list[tuple[int, str]] = []
        for hwnd, title in windows:
            if hwnd in seen:
                continue
            seen.add(hwnd)
            unique.append((hwnd, title))
        return unique

    def _rect_area(self, rect: tuple[int, int, int, int] | None) -> int:
        if rect is None:
            return 0
        left, top, right, bottom = rect
        return max(0, right - left) * max(0, bottom - top)
