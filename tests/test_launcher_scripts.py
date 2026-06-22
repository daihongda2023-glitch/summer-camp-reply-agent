from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherScriptsTest(unittest.TestCase):
    def test_powershell_launcher_stops_previous_workbench_processes(self):
        script = (ROOT / "scripts" / "start_agent_workbench.ps1").read_text(encoding="utf-8")

        self.assertIn("Stop-PreviousWorkbenchProcesses", script)
        self.assertIn("summer_camp_agent.workbench_web", script)
        self.assertIn("Name -like 'python*'", script)
        self.assertIn("Stop-Process", script)
        self.assertIn("netstat -ano", script)
        self.assertIn("8765..8799", script)
        self.assertIn("ProcessName -like 'python*'", script)

    def test_powershell_launcher_logs_loaded_workbench_module(self):
        script = (ROOT / "scripts" / "start_agent_workbench.ps1").read_text(encoding="utf-8")

        self.assertIn("Confirm-WorkbenchCodeVersion", script)
        self.assertIn("git -c safe.directory", script)
        self.assertIn("formatDecisionValue", script)
        self.assertIn("print('module='", script)

    def test_cmd_launcher_can_be_copied_to_desktop(self):
        launcher_paths = list(ROOT.glob("*Agent.cmd"))
        self.assertTrue(launcher_paths)

        script = launcher_paths[0].read_text(encoding="utf-8")

        self.assertIn("REPO_ROOT_B64", script)
        self.assertNotIn(r"D:\workspace\codex", script)
        self.assertIn(r"scripts\start_agent_workbench.ps1", script)
        self.assertIn("Start-Process", script)


if __name__ == "__main__":
    unittest.main()
