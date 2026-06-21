import unittest

from summer_camp_agent.workbench_gui import SummerCampWorkbenchApp


class WorkbenchGuiTest(unittest.TestCase):
    def test_workbench_app_class_is_importable(self):
        self.assertEqual(SummerCampWorkbenchApp.__name__, "SummerCampWorkbenchApp")

    def test_default_group_names_are_available(self):
        self.assertIn("夏令营咨询群", SummerCampWorkbenchApp.default_group_names())


if __name__ == "__main__":
    unittest.main()
