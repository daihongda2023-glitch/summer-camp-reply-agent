from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class WorkTraceStep:
    event_id: str
    group_name: str
    phase: str
    summary: str
    actor: str = "agent"
    action: str = ""
    outcome: str = ""
    reasoning: str = ""
    details: dict[str, object] = field(default_factory=dict)


class WorkTraceRecorder:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(self, step: WorkTraceStep) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trace_id": uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **asdict(step),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_work_trace(path: str | Path, limit: int = 200) -> list[dict[str, object]]:
    source = Path(path)
    if not source.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows[-limit:]
