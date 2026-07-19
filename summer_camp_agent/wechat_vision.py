from __future__ import annotations

import json
import inspect
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .chat_log_sanitizer import hash_identifier
from .workbench_models import ChatEvent


@dataclass(frozen=True)
class VisionMessage:
    message_id: str
    sender_alias: str
    content: str
    message_time: str
    region: dict[str, int]
    confidence: float
    source: str = "wechat_pc_vision"


@dataclass(frozen=True)
class VisionState:
    running: bool = False
    window_title: str = ""
    last_message: str = ""
    last_error: str = ""


@dataclass(frozen=True)
class VisionCaptureResult:
    status: str
    message: str
    events: list[ChatEvent]
    vision: VisionState


WINDOWS_OCR_SCRIPT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null

function Await-WinRT {
    param($Operation, [Type]$ResultType)
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
            $_.GetGenericArguments().Count -eq 1 -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -like 'IAsyncOperation*'
        } |
        Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:WECHAT_OCR_IMAGE_PATH)) ([Windows.Storage.StorageFile])
$stream = Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'Windows OCR language pack is unavailable.' }
$result = Await-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = @($result.Lines | ForEach-Object {
    $line = $_
    $words = @($line.Words)
    $left = ($words | ForEach-Object { $_.BoundingRect.X } | Measure-Object -Minimum).Minimum
    $top = ($words | ForEach-Object { $_.BoundingRect.Y } | Measure-Object -Minimum).Minimum
    $right = ($words | ForEach-Object { $_.BoundingRect.X + $_.BoundingRect.Width } | Measure-Object -Maximum).Maximum
    $bottom = ($words | ForEach-Object { $_.BoundingRect.Y + $_.BoundingRect.Height } | Measure-Object -Maximum).Maximum
    [ordered]@{
        text = $line.Text
        left = [int]$left
        top = [int]$top
        width = [int]($right - $left)
        height = [int]($bottom - $top)
    }
})
[ordered]@{
    width = [int]$bitmap.PixelWidth
    height = [int]$bitmap.PixelHeight
    lines = $lines
} | ConvertTo-Json -Depth 5 -Compress
"""


class WindowsOcrVisionRecognizer:
    def __init__(self, ocr_runner=None):
        self.ocr_runner = ocr_runner or self._run_windows_ocr
        self._message_states: dict[str, dict[str, int | str]] = {}

    def recognize(self, screenshot: bytes, *, window_title: str = "") -> list[VisionMessage]:
        if not screenshot:
            return []
        payload = self.ocr_runner(screenshot)
        width = max(1, int(payload.get("width") or 0))
        height = max(1, int(payload.get("height") or 0))
        candidates = []
        for raw_line in payload.get("lines") or []:
            line = self._normalize_line(raw_line)
            if line is None or not self._is_incoming_chat_line(line, width, height):
                continue
            candidates.append(line)
        if not candidates:
            return []

        latest_lines = self._latest_message_lines(candidates, width, height)
        latest_lines.sort(key=lambda line: (line["top"], line["left"]))
        content = "".join(line["text"] for line in latest_lines).strip()
        visible_occurrences = max(1, sum(1 for line in candidates if line["text"] == content))
        left = min(line["left"] for line in latest_lines)
        top = min(line["top"] for line in latest_lines)
        right = max(line["left"] + line["width"] for line in latest_lines)
        bottom = max(line["top"] + line["height"] for line in latest_lines)
        region = {"x": left, "y": top, "width": right - left, "height": bottom - top}
        return [
            VisionMessage(
                message_id=self._message_id(window_title, content, visible_occurrences),
                sender_alias="客户",
                content=content,
                message_time="",
                region=region,
                confidence=0.9,
            )
        ]

    def _message_id(self, window_title: str, content: str, visible_occurrences: int) -> str:
        state = self._message_states.get(window_title)
        is_new = (
            state is None
            or content != state["content"]
            or visible_occurrences > int(state["visible_occurrences"])
        )
        if is_new:
            sequence = int(state["sequence"]) + 1 if state is not None else 1
            state = {
                "content": content,
                "visible_occurrences": visible_occurrences,
                "sequence": sequence,
                "message_id": hash_identifier(f"{window_title}:{sequence}:{content}"),
            }
            self._message_states[window_title] = state
        return str(state["message_id"])

    @staticmethod
    def _latest_message_lines(candidates: list[dict[str, int | str]], width: int, height: int):
        ordered = sorted(candidates, key=lambda line: (int(line["top"]), int(line["left"])), reverse=True)
        latest = ordered[0]
        selected = [latest]
        current_top = int(latest["top"])
        anchor_left = int(latest["left"])
        max_gap = max(24, int(height * 0.04))
        max_left_shift = max(80, int(width * 0.12))
        for line in ordered[1:]:
            line_bottom = int(line["top"]) + int(line["height"])
            vertical_gap = current_top - line_bottom
            if vertical_gap < 0 or vertical_gap > max_gap:
                break
            if abs(int(line["left"]) - anchor_left) > max_left_shift:
                break
            selected.append(line)
            current_top = int(line["top"])
        return selected

    @staticmethod
    def _normalize_line(raw_line) -> dict[str, int | str] | None:
        if not isinstance(raw_line, dict):
            return None
        text = str(raw_line.get("text") or "").strip()
        if not text:
            return None
        if re.search(r"[\u4e00-\u9fff]", text):
            text = re.sub(r"\s+", "", text)
        else:
            text = re.sub(r"\s+", " ", text)
        text = text.replace("囗", "口")
        return {
            "text": text,
            "left": int(raw_line.get("left") or 0),
            "top": int(raw_line.get("top") or 0),
            "width": int(raw_line.get("width") or 0),
            "height": int(raw_line.get("height") or 0),
        }

    @staticmethod
    def _is_incoming_chat_line(line: dict[str, int | str], width: int, height: int) -> bool:
        text = str(line["text"])
        if re.fullmatch(r"\d{1,2}[:：]\d{2}", re.sub(r"\s+", "", text)):
            return False
        left = int(line["left"])
        top = int(line["top"])
        return width * 0.34 <= left <= width * 0.72 and height * 0.12 <= top <= height * 0.82

    @staticmethod
    def _run_windows_ocr(screenshot: bytes) -> dict:
        if sys.platform != "win32":
            raise OSError("截图文字识别仅支持 Windows。")
        image_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as image_file:
                image_file.write(screenshot)
                image_path = image_file.name
            env = os.environ.copy()
            env["WECHAT_OCR_IMAGE_PATH"] = image_path
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", WINDOWS_OCR_SCRIPT],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=20,
            )
            if completed.returncode != 0:
                raise OSError("Windows OCR 调用失败。")
            output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            if not output_lines:
                raise OSError("Windows OCR 未返回结果。")
            payload = json.loads(output_lines[-1])
            if not isinstance(payload, dict):
                raise OSError("Windows OCR 返回格式无效。")
            return payload
        except (json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            raise OSError("Windows OCR 识别超时或返回格式无效。") from exc
        finally:
            if image_path:
                Path(image_path).unlink(missing_ok=True)


class WeChatVisionObserver:
    def __init__(self, recognizer=None, min_confidence: float = 0.75):
        self.recognizer = recognizer or WindowsOcrVisionRecognizer()
        self.min_confidence = min_confidence
        self.seen_message_ids: set[str] = set()
        self.state = VisionState()

    def start(self) -> VisionState:
        self.state = VisionState(running=True, window_title=self.state.window_title)
        return self.state

    def stop(self) -> VisionState:
        self.state = VisionState(running=False, window_title=self.state.window_title)
        return self.state

    def capture_once(self, screenshot: bytes, *, window_title: str, group_name: str) -> VisionCaptureResult:
        try:
            recognize = self.recognizer.recognize
            signature = inspect.signature(recognize)
            if "window_title" in signature.parameters:
                messages = recognize(screenshot, window_title=window_title)
            else:
                messages = recognize(screenshot)
        except OSError:
            self.state = VisionState(
                running=self.state.running,
                window_title=window_title,
                last_message=self.state.last_message,
                last_error="截图文字识别失败，请确认 Windows 中文 OCR 可用。",
            )
            return VisionCaptureResult("error", self.state.last_error, [], self.state)
        high_confidence = [message for message in messages if message.confidence >= self.min_confidence]
        if not high_confidence and messages:
            self.state = VisionState(
                running=self.state.running,
                window_title=window_title,
                last_message=messages[0].content,
                last_error="识别置信度过低",
            )
            return VisionCaptureResult("low_confidence", "识别置信度过低，已拦截自动填入。", [], self.state)

        events: list[ChatEvent] = []
        for message in high_confidence:
            event_id = self._event_id(window_title, message)
            if event_id in self.seen_message_ids:
                continue
            self.seen_message_ids.add(event_id)
            events.append(self._to_event(event_id, window_title, group_name, message))

        last_message = high_confidence[0].content if high_confidence else ""
        self.state = VisionState(running=self.state.running, window_title=window_title, last_message=last_message)
        if events:
            return VisionCaptureResult("ok", f"已识别 {len(events)} 条新消息", events, self.state)
        return VisionCaptureResult("ok", "未识别到新的高置信消息", [], self.state)

    def _event_id(self, window_title: str, message: VisionMessage) -> str:
        return hash_identifier(f"{window_title}:{message.message_id}:{message.content}:{message.message_time}")

    def _to_event(self, event_id: str, window_title: str, group_name: str, message: VisionMessage) -> ChatEvent:
        return ChatEvent(
            event_id=event_id,
            group_id_hash=hash_identifier(window_title),
            group_name=group_name,
            sender_alias=message.sender_alias,
            sender_role="student",
            message_time=message.message_time,
            content=message.content,
            raw_type="text",
            source=message.source,
        )
