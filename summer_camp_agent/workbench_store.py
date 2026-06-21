from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .workbench_models import ReplyCandidate, ReplyLogEntry


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
