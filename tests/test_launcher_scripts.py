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

    def test_powershell_launcher_prepares_and_starts_weflow_hidden(self):
        script = (ROOT / "scripts" / "start_agent_workbench.ps1").read_text(encoding="utf-8")

        self.assertIn("Ensure-WeFlowConfig", script)
        self.assertIn("WeFlow-config.agent-backup.json", script)
        self.assertIn("httpApiEnabled", script)
        self.assertIn("httpApiToken", script)
        self.assertIn("RandomNumberGenerator", script)
        self.assertIn("Start-WeFlowHidden", script)
        self.assertIn("/api/v1/health", script)
        self.assertIn("5031", script)
        self.assertIn("weflow-dev.out", script)
        self.assertIn("weflow-dev.err", script)
        self.assertIn("-WindowStyle Hidden", script)
        self.assertNotIn("-WindowStyle Minimized", script)

    def test_powershell_launcher_starts_workbench_as_background_process(self):
        script = (ROOT / "scripts" / "start_agent_workbench.ps1").read_text(encoding="utf-8")

        self.assertIn("Start-AgentWorkbench", script)
        self.assertIn("RedirectStandardOutput", script)
        self.assertIn("RedirectStandardError", script)
        self.assertIn("workbench-web.out", script)
        self.assertIn("workbench-web.err", script)
        self.assertNotIn("& $pythonExe -B -m summer_camp_agent.workbench_web", script)

    def test_cmd_launcher_can_be_copied_to_desktop(self):
        launcher_paths = list(ROOT.glob("*Agent.cmd"))
        self.assertTrue(launcher_paths)

        script = launcher_paths[0].read_text(encoding="utf-8")

        self.assertIn("REPO_ROOT_B64", script)
        self.assertNotIn(r"D:\workspace\codex", script)
        self.assertIn(r"scripts\start_agent_workbench.ps1", script)
        self.assertIn("Start-Process", script)

    def test_desktop_launcher_starts_electron_app(self):
        script_path = ROOT / "scripts" / "start_desktop_app.ps1"
        self.assertTrue(script_path.exists())

        script = script_path.read_text(encoding="utf-8")

        self.assertIn("desktop", script)
        self.assertIn("npm.cmd", script)
        self.assertIn("run", script)
        self.assertIn("dev", script)
        self.assertIn("build:main", script)
        self.assertIn("--strictPort", script)
        self.assertIn("Test-LocalPortListening", script)
        self.assertIn("Stop-DesktopProcesses", script)
        self.assertIn("Stop-PortOwner", script)
        self.assertIn("Get-CimInstance Win32_Process", script)
        self.assertIn("vite", script)
        self.assertIn("summer_camp_agent", script)
        self.assertIn("workbench_server", script)
        self.assertIn("5178", script)
        self.assertIn("ELECTRON_RENDERER_URL", script)
        self.assertIn("-WindowStyle Hidden", script)


if __name__ == "__main__":
    unittest.main()
