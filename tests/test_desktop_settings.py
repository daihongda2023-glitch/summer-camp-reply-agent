import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.desktop_settings import DesktopSettings, DesktopSettingsStore


class DesktopSettingsTest(unittest.TestCase):
    def test_defaults_keep_main_window_minimal(self):
        settings = DesktopSettings()

        self.assertEqual(settings.window["width"], 380)
        self.assertEqual(settings.window["height"], 680)
        self.assertTrue(settings.main_view["show_target"])
        self.assertTrue(settings.main_view["show_recent_logs"])
        self.assertFalse(settings.main_view["show_status_detail"])
        self.assertTrue(settings.advanced_pages["messages"])
        self.assertFalse(settings.advanced_pages["rag"])

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
