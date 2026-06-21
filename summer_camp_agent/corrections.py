from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path


CORRECTION_PREFIXES = (
    "修正上个问题的回答结果：",
    "修正上个问题的回答结果:",
)


def parse_correction_command(text: str) -> str | None:
    stripped = text.strip()
    for prefix in CORRECTION_PREFIXES:
        if stripped.startswith(prefix):
            answer = stripped[len(prefix) :].strip()
            return answer or None
    return None


def save_local_override(question: str, answer: str, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    items = load_local_override_dicts(target)
    new_item = _build_override_item(question, answer)

    replaced = False
    for index, item in enumerate(items):
        if item.get("question") == question:
            items[index] = new_item
            replaced = True
            break
    if not replaced:
        items.insert(0, new_item)

    target.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def load_local_override_dicts(path: str | Path) -> list[dict[str, object]]:
    target = Path(path)
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _build_override_item(question: str, answer: str) -> dict[str, object]:
    today = date.today().isoformat()
    digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"local.override.{digest}",
        "stage": "桌面验证期",
        "intent": f"local.override.{digest}",
        "question": question,
        "question_aliases": [question],
        "keywords": [],
        "answer": answer,
        "source": "桌面验证修正",
        "source_date": today,
        "last_updated": today,
        "valid_until": "",
        "auto_reply": True,
        "needs_human_fallback": False,
        "human_fallback_reason": "",
        "owner": "本地验证",
    }
