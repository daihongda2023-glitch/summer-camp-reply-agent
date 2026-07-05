from __future__ import annotations

import ctypes
import ctypes.wintypes
from dataclasses import dataclass
import struct
import sys
from typing import Callable


@dataclass(frozen=True)
class WeChatWindowCapture:
    status: str
    message: str
    screenshot: bytes = b""
    window_title: str = ""


def is_wechat_window_title(title: str) -> bool:
    value = title.strip()
    if not value:
        return False
    if "企业微信" in value:
        return False
    return value == "微信" or value.endswith(" - 微信") or value.endswith("- 微信")


class WindowsWeChatWindowBackend:
    """定位普通微信窗口，并按窗口矩形截取一张 BMP 图像。"""

    SRCCOPY = 0x00CC0020
    DIB_RGB_COLORS = 0
    BI_RGB = 0

    def __init__(self):
        self.user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        self.gdi32 = ctypes.windll.gdi32 if sys.platform == "win32" else None
        if sys.platform == "win32":
            self._configure_win32_api()

    def _configure_win32_api(self) -> None:
        self.user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        self.user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
        self.user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
        self.user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
        self.user32.GetWindowRect.restype = ctypes.wintypes.BOOL
        self.user32.GetDC.argtypes = [ctypes.wintypes.HWND]
        self.user32.GetDC.restype = ctypes.wintypes.HDC
        self.user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
        self.gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC
        self.gdi32.CreateCompatibleBitmap.argtypes = [ctypes.wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi32.CreateCompatibleBitmap.restype = ctypes.wintypes.HBITMAP
        self.gdi32.SelectObject.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HGDIOBJ]
        self.gdi32.SelectObject.restype = ctypes.wintypes.HGDIOBJ
        self.gdi32.BitBlt.argtypes = [
            ctypes.wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.wintypes.DWORD,
        ]
        self.gdi32.BitBlt.restype = ctypes.wintypes.BOOL
        self.gdi32.GetDIBits.argtypes = [
            ctypes.wintypes.HDC,
            ctypes.wintypes.HBITMAP,
            ctypes.wintypes.UINT,
            ctypes.wintypes.UINT,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.wintypes.UINT,
        ]
        self.gdi32.GetDIBits.restype = ctypes.c_int
        self.gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
        self.gdi32.DeleteObject.restype = ctypes.wintypes.BOOL
        self.gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
        self.gdi32.DeleteDC.restype = ctypes.wintypes.BOOL

    def capture_wechat_window(self) -> WeChatWindowCapture:
        if sys.platform != "win32":
            return WeChatWindowCapture("error", "当前平台不支持自动截取微信窗口。")

        hwnd, title = self.find_wechat_window()
        if not hwnd:
            return WeChatWindowCapture("not_found", "未找到可见的微信窗口，请先打开微信 PC。")

        screenshot = self.capture_window(hwnd)
        if not screenshot:
            return WeChatWindowCapture("error", "已找到微信窗口，但截图失败。", window_title=title)
        return WeChatWindowCapture("ok", "已截取微信窗口。", screenshot=screenshot, window_title=title)

    def find_wechat_window(self) -> tuple[int, str]:
        active_hwnd = self.user32.GetForegroundWindow()
        active_title = self.window_title(active_hwnd)
        if self.is_usable_wechat_window(active_hwnd, active_title):
            return active_hwnd, active_title

        found: list[tuple[int, str]] = []

        def collect(hwnd: int) -> bool:
            title = self.window_title(hwnd)
            if self.is_usable_wechat_window(hwnd, title):
                found.append((hwnd, title))
                return False
            return True

        self.enum_windows(collect)
        return found[0] if found else (0, "")

    def enum_windows(self, visitor: Callable[[int], bool]) -> None:
        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            return bool(visitor(int(hwnd)))

        self.user32.EnumWindows(enum_proc_type(callback), 0)

    def is_usable_wechat_window(self, hwnd: int, title: str) -> bool:
        if not hwnd or not is_wechat_window_title(title):
            return False
        if not self.user32.IsWindowVisible(hwnd):
            return False
        left, top, right, bottom = self.window_rect(hwnd)
        return (right - left) >= 100 and (bottom - top) >= 100

    def window_title(self, hwnd: int) -> str:
        if not hwnd:
            return ""
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = ctypes.wintypes.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom

    def capture_window(self, hwnd: int) -> bytes:
        left, top, right, bottom = self.window_rect(hwnd)
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return b""

        screen_dc = self.user32.GetDC(0)
        memory_dc = self.gdi32.CreateCompatibleDC(screen_dc)
        bitmap = self.gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not screen_dc or not memory_dc or not bitmap:
            return b""
        old_bitmap = self.gdi32.SelectObject(memory_dc, bitmap)
        try:
            copied = self.gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, left, top, self.SRCCOPY)
            if not copied:
                return b""
            return self._bitmap_to_bmp(memory_dc, bitmap, width, height)
        finally:
            self.gdi32.SelectObject(memory_dc, old_bitmap)
            self.gdi32.DeleteObject(bitmap)
            self.gdi32.DeleteDC(memory_dc)
            self.user32.ReleaseDC(0, screen_dc)

    def _bitmap_to_bmp(self, dc, bitmap, width: int, height: int) -> bytes:
        row_size = ((width * 24 + 31) // 32) * 4
        image_size = row_size * height
        bmi = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 24, self.BI_RGB, image_size, 0, 0, 0, 0)
        bmi_buffer = ctypes.create_string_buffer(bmi)
        pixels = ctypes.create_string_buffer(image_size)
        lines = self.gdi32.GetDIBits(dc, bitmap, 0, height, pixels, bmi_buffer, self.DIB_RGB_COLORS)
        if lines != height:
            return b""
        file_header = struct.pack("<2sIHHI", b"BM", 14 + 40 + image_size, 0, 0, 14 + 40)
        return file_header + bmi + pixels.raw
