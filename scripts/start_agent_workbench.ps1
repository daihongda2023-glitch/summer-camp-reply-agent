$ErrorActionPreference = 'Stop'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$launchLog = Join-Path $repoRoot 'data\agent_launcher.log'

function Get-WorkbenchProcessIdsFromCommandLine {
    $target = 'summer_camp_agent.workbench_web'
    try {
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.ProcessId -ne $PID -and
                $_.Name -like 'python*' -and
                $_.CommandLine -and
                $_.CommandLine -like "*$target*"
            } |
            ForEach-Object { [int]$_.ProcessId }
    } catch {
        Write-Host "[Agent] Could not inspect process command lines: $($_.Exception.Message)"
        @()
    }
}

function Get-ListeningProcessIdsFromNetstat {
    param(
        [Parameter(Mandatory = $true)]
        [int[]]$Ports
    )

    $processIds = @()
    try {
        $portSet = @{}
        foreach ($port in $Ports) {
            $portSet[$port] = $true
        }

        $lines = & netstat -ano -p tcp
        foreach ($line in $lines) {
            if ($line -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
                $port = [int]$Matches[1]
                if ($portSet.ContainsKey($port)) {
                    $processId = [int]$Matches[2]
                    $processIds += $processId
                }
            }
        }
    } catch {
        Write-Host "[Agent] Could not inspect listening ports with netstat: $($_.Exception.Message)"
    }
    $processIds
}

function Get-WorkbenchProcessIdsFromPorts {
    $processIds = @()
    $workbenchPorts = 8765..8799

    foreach ($processId in (Get-ListeningProcessIdsFromNetstat -Ports $workbenchPorts)) {
        if ($processId -eq $PID) {
            continue
        }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -like 'python*') {
            $processIds += [int]$processId
        }
    }

    $processIds
}

function Stop-PreviousWorkbenchProcesses {
    $processIds = @(
        Get-WorkbenchProcessIdsFromCommandLine
        Get-WorkbenchProcessIdsFromPorts
    ) | Where-Object { $_ } | Sort-Object -Unique

    if (-not $processIds -or $processIds.Count -eq 0) {
        Write-Host '[Agent] No previous workbench process found.'
        return @()
    }

    $stoppedProcessIds = @()
    foreach ($processId in $processIds) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "[Agent] Stopped previous workbench process: $processId"
            $stoppedProcessIds += $processId
        } catch {
            Write-Host "[Agent] Could not stop process ${processId}: $($_.Exception.Message)"
        }
    }
    Start-Sleep -Milliseconds 1500
    return $stoppedProcessIds
}

function Start-AgentTranscript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    $logDir = Split-Path -Parent $LogPath
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }

    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            Start-Transcript -Path $LogPath -Force | Out-Null
            Write-Host "[Agent] Launcher log: $LogPath"
            return $true
        } catch {
            if ($attempt -eq 10) {
                Write-Host "[Agent] Could not start launcher log: $($_.Exception.Message)"
                return $false
            }
            Start-Sleep -Milliseconds 300
        }
    }
}

function Confirm-WorkbenchCodeVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    # git -c safe.directory is used so desktop launches trust this repo path.
    try {
        $gitCommit = (& git -c "safe.directory=$RepoRoot" rev-parse --short HEAD 2>$null)
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($gitCommit)) {
            Write-Host "[Agent] Git commit: $($gitCommit.Trim())"
        }
    } catch {
        Write-Host "[Agent] Git commit check skipped: $($_.Exception.Message)"
    }

$probe = @'
from pathlib import Path
import summer_camp_agent.workbench_web as workbench_web

print('module=' + str(Path(workbench_web.__file__).resolve()))
print('decision_mapping=' + ('ok' if 'formatDecisionValue' in workbench_web.WORKBENCH_HTML else 'missing'))
'@
    $probeOutput = & $PythonExe -B -c $probe 2>&1
    $probeExitCode = $LASTEXITCODE
    foreach ($line in $probeOutput) {
        Write-Host "[Agent] $line"
    }
    if ($probeExitCode -ne 0) {
        throw "Failed to import the workbench module before launch. Probe exit code: $probeExitCode"
    }
    if ($probeOutput -notcontains 'decision_mapping=ok') {
        throw 'Workbench HTML mapping check failed. Please confirm the launcher is using the latest source code.'
    }
}

$stoppedProcessIds = @(Stop-PreviousWorkbenchProcesses)
Start-AgentTranscript -LogPath $launchLog | Out-Null
foreach ($processId in $stoppedProcessIds) {
    Write-Host "[Agent] Confirmed stopped previous workbench process before launch: $processId"
}

$weflowConfigPath = Join-Path $env:APPDATA 'weflow\WeFlow-config.json'
if (-not (Test-Path -LiteralPath $weflowConfigPath)) {
    throw "WeFlow config file not found: $weflowConfigPath. Please start WeFlow and enable the local API first."
}

try {
    $weflowConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $weflowConfigPath | ConvertFrom-Json
} catch {
    throw "WeFlow config file is not valid JSON. Please restart WeFlow or save the API settings again."
}

$token = [string]$weflowConfig.httpApiToken
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "WeFlow API token is missing. Please enable the local API in WeFlow settings."
}
$env:WEFLOW_API_TOKEN = $token

$pythonCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
    (Join-Path $env:ProgramFiles 'Python312\python.exe'),
    (Join-Path $env:ProgramFiles 'Python311\python.exe')
)

$pythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExe) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $pythonExe = $pythonCommand.Source
    }
}

if (-not $pythonExe -or -not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python 3.10 or later was not found."
}

Write-Host '[Agent] WeFlow API token loaded from config.'
Write-Host "[Agent] Python: $pythonExe"
Confirm-WorkbenchCodeVersion -PythonExe $pythonExe -RepoRoot $repoRoot
Write-Host '[Agent] Starting summer camp Agent workbench...'

& $pythonExe -B -m summer_camp_agent.workbench_web
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
