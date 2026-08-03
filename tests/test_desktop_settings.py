import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.desktop_settings import (
    OPERATION_PROFILE_ASSISTED,
    OPERATION_PROFILE_AUTOMATIC,
    OPERATION_PROFILE_SAFE_REVIEW,
    DesktopSettings,
    DesktopSettingsStore,
    apply_operation_profile,
    resolve_operation_profile,
)


class DesktopSettingsTest(unittest.TestCase):
    def test_defaults_fit_complete_workbench(self):
        settings = DesktopSettings()

        self.assertEqual(settings.window["width"], 1180)
        self.assertEqual(settings.window["height"], 760)
        self.assertEqual(settings.window["min_width"], 960)
        self.assertEqual(settings.window["min_height"], 680)
        self.assertTrue(settings.main_view["show_target"])
        self.assertTrue(settings.main_view["show_recent_logs"])
        self.assertFalse(settings.main_view["show_status_detail"])
        self.assertTrue(settings.advanced_pages["messages"])
        self.assertFalse(settings.advanced_pages["rag"])

    def test_operation_profile_resolves_from_existing_wechat_switches(self):
        self.assertEqual(
            resolve_operation_profile("manual_confirm", True),
            OPERATION_PROFILE_SAFE_REVIEW,
        )
        self.assertEqual(
            resolve_operation_profile("manual_confirm", False),
            OPERATION_PROFILE_ASSISTED,
        )
        self.assertEqual(
            resolve_operation_profile("auto_send", False),
            OPERATION_PROFILE_AUTOMATIC,
        )

    def test_operation_profile_applies_without_losing_other_wechat_settings(self):
        original = {"group_name": "测试群", "poll_interval_seconds": 8}

        safe = apply_operation_profile(original, OPERATION_PROFILE_SAFE_REVIEW)
        assisted = apply_operation_profile(original, OPERATION_PROFILE_ASSISTED)
        automatic = apply_operation_profile(original, OPERATION_PROFILE_AUTOMATIC)

        self.assertEqual(safe["group_name"], "测试群")
        self.assertEqual(
            (safe["send_mode"], safe["debug_review_mode"]),
            ("manual_confirm", True),
        )
        self.assertEqual(
            (assisted["send_mode"], assisted["debug_review_mode"]),
            ("manual_confirm", False),
        )
        self.assertEqual(
            (automatic["send_mode"], automatic["debug_review_mode"]),
            ("auto_send", False),
        )

    def test_operation_profile_rejects_unknown_value(self):
        with self.assertRaisesRegex(ValueError, "运行模式"):
            apply_operation_profile({}, "unknown")

    def test_store_round_trips_visibility_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "desktop_settings.json"
            store = DesktopSettingsStore(path)
            settings = DesktopSettings.from_dict(
                {
                    "main_view": {
                        "show_target": False,
                        "show_recent_logs": True,
                        "show_history_entry": False,
                        "show_status_detail": True,
                        "show_assist_actions": False,
                    },
                    "advanced_pages": {
                        "messages": True,
                        "candidates": False,
                        "work_trace": True,
                        "rag": True,
                    },
                }
            )

            store.save(settings)
            loaded = store.load()

        self.assertFalse(loaded.main_view["show_target"])
        self.assertTrue(loaded.main_view["show_status_detail"])
        self.assertFalse(loaded.advanced_pages["candidates"])
        self.assertTrue(loaded.advanced_pages["rag"])


if __name__ == "__main__":
    unittest.main()
