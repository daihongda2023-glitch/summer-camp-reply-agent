from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock

from .workbench_models import ChatEvent, ReplyCandidate, ReplyLogEntry


class WorkbenchInboxStore:
    def __init__(self, path: str | Path, max_items: int = 500):
        self.path = Path(path)
        self.max_items = max_items
        self._lock = RLock()

    def load(self) -> list[ChatEvent]:
        with self._lock:
            if not self.path.exists():
                return []
            events: list[ChatEvent] = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    payload = json.loads(line)
                    events.append(ChatEvent(**payload))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
            return events[-self.max_items :]

    def upsert(self, event: ChatEvent) -> None:
        with self._lock:
            events = [
                item
                for item in self.load()
                if item.event_id != event.event_id
            ]
            self._replace([*events, event][-self.max_items :])

    def remove(self, event_id: str) -> None:
        with self._lock:
            self._replace(
                [
                    item
                    for item in self.load()
                    if item.event_id != event_id
                ]
            )

    def _replace(self, events: list[ChatEvent]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            "".join(
                json.dumps(asdict(event), ensure_ascii=False) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)


class ReplyCandidateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, candidate: ReplyCandidate) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(candidate), ensure_ascii=False) + "\n")


class ReplyLogStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, entry: ReplyLogEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
