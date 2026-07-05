from __future__ import annotations

from dataclasses import dataclass

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


class StaticVisionRecognizer:
    def recognize(self, screenshot: bytes) -> list[VisionMessage]:
        return []


class WeChatVisionObserver:
    def __init__(self, recognizer=None, min_confidence: float = 0.75):
        self.recognizer = recognizer or StaticVisionRecognizer()
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
        messages = self.recognizer.recognize(screenshot)
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
        region = ",".join(f"{key}:{message.region.get(key, 0)}" for key in sorted(message.region))
        return hash_identifier(f"{window_title}:{message.message_id}:{message.content}:{message.message_time}:{region}")

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
