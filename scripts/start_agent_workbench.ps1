$ErrorActionPreference = 'Stop'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

$launchLog = Join-Path $repoRoot 'data\agent_launcher.log'
$weflowRoot = 'D:\github\WeFlow'
$weflowHealthUrl = 'http://127.0.0.1:5031/api/v1/health'
$weflowOutLog = Join-Path $weflowRoot 'weflow-dev.out'
$weflowErrLog = Join-Path $weflowRoot 'weflow-dev.err'
$workbenchOutLog = Join-Path $repoRoot 'data\workbench-web.out'
$workbenchErrLog = Join-Path $repoRoot 'data\workbench-web.err'

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

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Object,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
        return
    }
    Add-Member -InputObject $Object -NotePropertyName $Name -NotePropertyValue $Value
}

function New-WeFlowApiToken {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Ensure-WeFlowConfig {
    $configDir = Join-Path $env:APPDATA 'weflow'
    $configPath = Join-Path $configDir 'WeFlow-config.json'
    $backupPath = Join-Path $configDir 'WeFlow-config.agent-backup.json'

    if (-not (Test-Path -LiteralPath $configDir)) {
        New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    }

    if (Test-Path -LiteralPath $configPath) {
        Copy-Item -LiteralPath $configPath -Destination $backupPath -Force
        try {
            $config = Get-Content -Raw -Encoding UTF8 -LiteralPath $configPath | ConvertFrom-Json
        } catch {
            throw "WeFlow config file is not valid JSON: $configPath"
        }
        if ($null -eq $config) {
            $config = [pscustomobject]@{}
        }
    } else {
        $config = [pscustomobject]@{}
    }

    $token = [string]$config.httpApiToken
    $generatedToken = $false
    if ([string]::IsNullOrWhiteSpace($token)) {
        $token = New-WeFlowApiToken
        $generatedToken = $true
    }

    Set-JsonProperty -Object $config -Name 'httpApiEnabled' -Value $true
    Set-JsonProperty -Object $config -Name 'httpApiHost' -Value '127.0.0.1'
    Set-JsonProperty -Object $config -Name 'httpApiPort' -Value 5031
    Set-JsonProperty -Object $config -Name 'silentStartup' -Value $true
    Set-JsonProperty -Object $config -Name 'windowCloseBehavior' -Value 'tray'
    Set-JsonProperty -Object $config -Name 'httpApiToken' -Value $token

    $json = $config | ConvertTo-Json -Depth 50
    [System.IO.File]::WriteAllText($configPath, $json, [System.Text.Encoding]::UTF8)

    if ($generatedToken) {
        Write-Host '[Agent] WeFlow local API token generated and saved to the user config.'
    } else {
        Write-Host '[Agent] WeFlow local API token loaded from the user config.'
    }
    Write-Host "[Agent] WeFlow config prepared: $configPath"
    return $token
}

function Test-WeFlowHealth {
    try {
        $response = Invoke-WebRequest -Uri $weflowHealthUrl -UseBasicParsing -TimeoutSec 2
        return [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 300
    } catch {
        return $false
    }
}

function Wait-WeFlowHealth {
    param(
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-WeFlowHealth) {
            Write-Host "[Agent] WeFlow health is ready: $weflowHealthUrl"
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-WeFlowHidden {
    if (Test-WeFlowHealth) {
        Write-Host "[Agent] WeFlow health already available: $weflowHealthUrl"
        return
    }
    if (-not (Test-Path -LiteralPath $weflowRoot)) {
        throw "WeFlow root was not found: $weflowRoot"
    }

    New-Item -ItemType Directory -Force -Path $weflowRoot | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $weflowRoot 'node_modules'))) {
        Write-Host '[Agent] WeFlow dependencies are missing. Running npm install in hidden mode...'
        $install = Start-Process -FilePath 'npm.cmd' `
            -ArgumentList @('install') `
            -WorkingDirectory $weflowRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $weflowOutLog `
            -RedirectStandardError $weflowErrLog `
            -PassThru `
            -Wait
        if ($install.ExitCode -ne 0) {
            throw "WeFlow npm install failed. See logs: $weflowOutLog / $weflowErrLog"
        }
    }

    Write-Host "[Agent] Starting WeFlow hidden. Logs: $weflowOutLog / $weflowErrLog"
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/d', '/s', '/c', 'npm.cmd run electron:dev') `
        -WorkingDirectory $weflowRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $weflowOutLog `
        -RedirectStandardError $weflowErrLog | Out-Null

    if (-not (Wait-WeFlowHealth -TimeoutSeconds 30)) {
        throw "WeFlow health check timed out: $weflowHealthUrl. See logs: $weflowOutLog / $weflowErrLog"
    }
}

function Resolve-PythonExe {
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
        throw 'Python 3.10 or later was not found.'
    }
    return $pythonExe
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

function Start-AgentWorkbench {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe
    )

    Write-Host "[Agent] Starting summer camp Agent workbench hidden. Logs: $workbenchOutLog / $workbenchErrLog"
    $process = Start-Process -FilePath $PythonExe `
        -ArgumentList @('-B', '-m', 'summer_camp_agent.workbench_web') `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $workbenchOutLog `
        -RedirectStandardError $workbenchErrLog `
        -PassThru
    Write-Host "[Agent] Workbench process started: $($process.Id)"
}

$transcriptStarted = $false
try {
    $stoppedProcessIds = @(Stop-PreviousWorkbenchProcesses)
    $transcriptStarted = Start-AgentTranscript -LogPath $launchLog
    foreach ($processId in $stoppedProcessIds) {
        Write-Host "[Agent] Confirmed stopped previous workbench process before launch: $processId"
    }

    $token = Ensure-WeFlowConfig
    $env:WEFLOW_API_TOKEN = $token
    $env:WEFLOW_CONFIG_PATH = Join-Path (Join-Path $env:APPDATA 'weflow') 'WeFlow-config.json'

    Start-WeFlowHidden

    $pythonExe = Resolve-PythonExe
    Write-Host "[Agent] Python: $pythonExe"
    Confirm-WorkbenchCodeVersion -PythonExe $pythonExe -RepoRoot $repoRoot
    Start-AgentWorkbench -PythonExe $pythonExe
    Write-Host '[Agent] Launcher completed. Background services will keep running.'
} catch {
    Write-Host "[Agent] Launcher failed: $($_.Exception.Message)"
    exit 1
} finally {
    if ($transcriptStarted) {
        try {
            Stop-Transcript | Out-Null
        } catch {
        }
    }
}
