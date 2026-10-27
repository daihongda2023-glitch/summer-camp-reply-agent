import unittest

from summer_camp_agent.workbench_gui import SummerCampWorkbenchApp
from summer_camp_agent.workbench_models import GroupConfig
from summer_camp_agent.workbench_session import WorkbenchSession


class WorkbenchGuiTest(unittest.TestCase):
    def test_workbench_app_class_is_importable(self):
        self.assertEqual(SummerCampWorkbenchApp.__name__, "SummerCampWorkbenchApp")

    def test_default_group_names_are_available(self):
        self.assertIn("夏令营咨询群", SummerCampWorkbenchApp.default_group_names())

    def test_demo_events_cover_common_mvp_paths(self):
        events = SummerCampWorkbenchApp.demo_events()

        self.assertGreaterEqual(len(events), 4)
        self.assertTrue(any("报名入口" in event.content for event in events))
        self.assertTrue(any("我被录取" in event.content for event in events))
        self.assertTrue(any("收到" in event.content for event in events))

    def test_format_item_summary_shows_processing_state(self):
        session = WorkbenchSession(GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]))
        item = session.process_event(SummerCampWorkbenchApp.demo_events()[0])

        summary = SummerCampWorkbenchApp.format_item_summary(item)

        self.assertIn("待审核", summary)
        self.assertIn("报名入口在哪里", summary)


if __name__ == "__main__":
    unittest.main()
