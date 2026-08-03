from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_DESKTOP_SETTINGS_PATH = Path(__file__).resolve().parents[1] / "data" / "desktop_settings.json"

OPERATION_PROFILE_SAFE_REVIEW = "safe_review"
OPERATION_PROFILE_ASSISTED = "assisted"
OPERATION_PROFILE_AUTOMATIC = "automatic"
OPERATION_PROFILES = {
    OPERATION_PROFILE_SAFE_REVIEW,
    OPERATION_PROFILE_ASSISTED,
    OPERATION_PROFILE_AUTOMATIC,
}


def resolve_operation_profile(send_mode: str, debug_review_mode: bool) -> str:
    if debug_review_mode:
        return OPERATION_PROFILE_SAFE_REVIEW
    if send_mode == "auto_send":
        return OPERATION_PROFILE_AUTOMATIC
    return OPERATION_PROFILE_ASSISTED


def apply_operation_profile(
    wechat_settings: dict[str, Any],
    operation_profile: str,
) -> dict[str, Any]:
    if operation_profile not in OPERATION_PROFILES:
        raise ValueError(f"不支持的运行模式：{operation_profile}")
    updated = dict(wechat_settings)
    updated["send_mode"] = (
        "auto_send"
        if operation_profile == OPERATION_PROFILE_AUTOMATIC
        else "manual_confirm"
    )
    updated["debug_review_mode"] = operation_profile == OPERATION_PROFILE_SAFE_REVIEW
    return updated


def _bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    if key not in raw:
        return default
    return bool(raw[key])


@dataclass(frozen=True)
class DesktopSettings:
    window: dict[str, int] = field(
        default_factory=lambda: {
            "width": 1180,
            "height": 760,
            "min_width": 960,
            "min_height": 680,
            "settings_width": 900,
            "settings_height": 720,
        }
    )
    main_view: dict[str, bool] = field(
        default_factory=lambda: {
            "show_target": True,
            "show_recent_logs": True,
            "show_history_entry": True,
            "show_status_detail": False,
            "show_assist_actions": False,
        }
    )
    advanced_pages: dict[str, bool] = field(
        default_factory=lambda: {
            "messages": True,
            "candidates": True,
            "work_trace": True,
            "rag": False,
        }
    )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DesktopSettings":
        defaults = cls()
        raw_window = raw.get("window") if isinstance(raw.get("window"), dict) else {}
        window = {
            key: int(raw_window.get(key, value) or value)
            for key, value in defaults.window.items()
        }
        window["width"] = max(960, window["width"])
        window["height"] = max(680, window["height"])

        raw_main = raw.get("main_view") if isinstance(raw.get("main_view"), dict) else {}
        main_view = {
            key: _bool(raw_main, key, value)
            for key, value in defaults.main_view.items()
        }

        raw_pages = raw.get("advanced_pages") if isinstance(raw.get("advanced_pages"), dict) else {}
        advanced_pages = {
            key: _bool(raw_pages, key, value)
            for key, value in defaults.advanced_pages.items()
        }
        return cls(window=window, main_view=main_view, advanced_pages=advanced_pages)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DesktopSettingsStore:
    def __init__(self, path: str | Path = DEFAULT_DESKTOP_SETTINGS_PATH):
        self.path = Path(path)

    def load(self) -> DesktopSettings:
        if not self.path.exists():
            return DesktopSettings()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return DesktopSettings()
        return DesktopSettings.from_dict(raw)

    def save(self, settings: DesktopSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
