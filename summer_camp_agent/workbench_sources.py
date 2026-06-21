from __future__ import annotations

import json
from pathlib import Path

from .workbench_models import ChatEvent


class ChatSourceError(RuntimeError):
    pass


class JsonlChatSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load_events(self) -> list[ChatEvent]:
        if not self.path.exists():
            raise ChatSourceError(f"聊天记录文件不存在：{self.path}")

        events: list[ChatEvent] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                events.append(
                    ChatEvent(
                        event_id=str(raw.get("platform_message_id_hash") or raw.get("event_id") or ""),
                        group_id_hash=str(raw.get("group_id_hash") or ""),
                        group_name=str(raw.get("group_name") or ""),
                        sender_alias=str(raw.get("sender_alias") or ""),
                        sender_role=str(raw.get("sender_role") or "unknown"),
                        message_time=str(raw.get("message_time") or ""),
                        content=str(raw.get("content") or ""),
                        raw_type=str(raw.get("raw_type") or "text"),
                        source=str(raw.get("source") or "jsonl"),
                    )
                )
        return events
