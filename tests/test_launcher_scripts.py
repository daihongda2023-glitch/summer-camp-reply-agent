import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SCRIPT = ROOT / "scripts" / "start_agent_workbench.ps1"
POWERSHELL_EXE = shutil.which("powershell.exe") or shutil.which("powershell")


def run_powershell(script):
    if not POWERSHELL_EXE:
        raise AssertionError("PowerShell executable was not found")

    env = os.environ.copy()
    env["LAUNCHER_SCRIPT_PATH"] = str(LAUNCHER_SCRIPT)
    result = subprocess.run(
        [POWERSHELL_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"PowerShell failed with exit code {result.returncode}:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


class LauncherScriptsTest(unittest.TestCase):
    def test_powershell_launcher_stops_previous_workbench_processes(self):
        script = (ROOT / "scripts" / "start_agent_workbench.ps1").read_text(encoding="utf-8")

        self.assertIn("Stop-PreviousWorkbenchProcesses", script)
        self.assertIn("summer_camp_agent.workbench_server", script)
        self.assertIn("Name -like 'python*'", script)
        self.assertIn("Stop-Process", script)
        self.assertIn("netstat -ano", script)
        self.assertIn("8765..8799", script)
        self.assertIn("ProcessName -like 'python*'", script)

    def test_powershell_launcher_checks_desktop_api_module(self):
        script = (ROOT / "scripts" / "start_agent_workbench.ps1").read_text(encoding="utf-8")

        self.assertIn("Confirm-WorkbenchCodeVersion", script)
        self.assertIn("git -c safe.directory", script)
        self.assertIn("desktop_api=ok", script)
        self.assertIn("workbench_server", script)
        self.assertIn("print('module='", script)

    def test_powershell_launcher_only_prepares_and_starts_weflow_when_opted_in(self):
        script = LAUNCHER_SCRIPT.read_text(encoding="utf-8")

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

    def test_powershell_launcher_weflow_opt_in_truth_table(self):
        output = run_powershell(
            r"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:LAUNCHER_SCRIPT_PATH,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw ($parseErrors | ForEach-Object Message | Out-String)
}
$functions = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Test-WeFlowAutoStartEnabled'
}, $true))
if ($functions.Count -ne 1) {
    throw "Expected one Test-WeFlowAutoStartEnabled function, found $($functions.Count)."
}
. ([scriptblock]::Create($functions[0].Extent.Text))

[ordered]@{
    unset = [bool](Test-WeFlowAutoStartEnabled -Value $null)
    zero = [bool](Test-WeFlowAutoStartEnabled -Value '0')
    trueString = [bool](Test-WeFlowAutoStartEnabled -Value 'true')
    one = [bool](Test-WeFlowAutoStartEnabled -Value '1')
} | ConvertTo-Json -Compress
"""
        )

        self.assertEqual(
            {"unset": False, "zero": False, "trueString": False, "one": True},
            json.loads(output),
        )

    def test_powershell_launcher_ast_keeps_weflow_calls_in_opt_in_branch(self):
        output = run_powershell(
            r"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:LAUNCHER_SCRIPT_PATH,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw ($parseErrors | ForEach-Object Message | Out-String)
}

$gates = @($ast.FindAll({
    param($node)
    if ($node -isnot [System.Management.Automation.Language.IfStatementAst]) {
        return $false
    }
    $conditionCommands = @($node.Clauses[0].Item1.FindAll({
        param($candidate)
        $candidate -is [System.Management.Automation.Language.CommandAst] -and
            $candidate.GetCommandName() -eq 'Test-WeFlowAutoStartEnabled'
    }, $true))
    return $conditionCommands.Count -eq 1
}, $true))
if ($gates.Count -ne 1) {
    throw "Expected one WeFlow opt-in gate, found $($gates.Count)."
}

$gate = $gates[0]
$optInBranch = $gate.Clauses[0].Item2
$weflowCalls = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -in @('Ensure-WeFlowConfig', 'Start-WeFlowHidden')
}, $true))

function Test-IsWithinAst {
    param(
        [System.Management.Automation.Language.Ast]$Node,
        [System.Management.Automation.Language.Ast]$Ancestor
    )
    while ($null -ne $Node) {
        if ([object]::ReferenceEquals($Node, $Ancestor)) {
            return $true
        }
        $Node = $Node.Parent
    }
    return $false
}

$outsideOptIn = @($weflowCalls | Where-Object { -not (Test-IsWithinAst $_ $optInBranch) })
$elseCalls = @($weflowCalls | Where-Object { Test-IsWithinAst $_ $gate.ElseClause })
$conditionVariables = @($gate.Clauses[0].Item1.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.VariableExpressionAst] -and
        $node.VariablePath.UserPath -eq 'env:SUMMER_CAMP_AGENT_START_WEFLOW'
}, $true))
$skipMessages = @($gate.ElseClause.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
        $node.Value -like '*WeFlow startup skipped by default*'
}, $true))

[ordered]@{
    callNames = @($weflowCalls | ForEach-Object { $_.GetCommandName() })
    outsideOptInCount = $outsideOptIn.Count
    elseCallCount = $elseCalls.Count
    conditionVariableCount = $conditionVariables.Count
    skipMessageCount = $skipMessages.Count
} | ConvertTo-Json -Compress
"""
        )
        structure = json.loads(output)

        self.assertCountEqual(["Ensure-WeFlowConfig", "Start-WeFlowHidden"], structure["callNames"])
        self.assertEqual(0, structure["outsideOptInCount"])
        self.assertEqual(0, structure["elseCallCount"])
        self.assertEqual(1, structure["conditionVariableCount"])
        self.assertEqual(1, structure["skipMessageCount"])

    def test_powershell_launcher_starts_desktop_app(self):
        script = (ROOT / "scripts" / "start_agent_workbench.ps1").read_text(encoding="utf-8")

        self.assertIn("Start-DesktopApp", script)
        self.assertIn("start_desktop_app.ps1", script)
        self.assertIn("Desktop app", script)
        self.assertNotIn("& $pythonExe -B -m summer_camp_agent.workbench_web", script)
        self.assertNotIn("summer_camp_agent.workbench_web", script)

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
