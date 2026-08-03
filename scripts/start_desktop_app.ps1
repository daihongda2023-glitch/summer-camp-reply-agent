$ErrorActionPreference = 'Stop'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$desktopRoot = Join-Path $repoRoot 'desktop'
$desktopOutLog = Join-Path $repoRoot 'data\desktop-electron.out'
$desktopErrLog = Join-Path $repoRoot 'data\desktop-electron.err'
$viteOutLog = Join-Path $repoRoot 'data\desktop-vite.out'
$viteErrLog = Join-Path $repoRoot 'data\desktop-vite.err'

function Test-LocalPortListening {
    param([int]$Port)

    $matches = netstat -ano | Select-String -Pattern "127\.0\.0\.1:$Port\s+0\.0\.0\.0:0\s+LISTENING"
    return $null -ne $matches
}

function Stop-PortOwner {
    param([int]$Port)

    $lines = netstat -ano | Select-String -Pattern "127\.0\.0\.1:$Port\s+0\.0\.0\.0:0\s+LISTENING"
    foreach ($line in $lines) {
        $parts = ($line.ToString() -split '\s+') | Where-Object { $_ }
        if ($parts.Length -lt 5) {
            continue
        }
        $processId = [int]$parts[-1]
        if ($processId -gt 0) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-DesktopProcesses {
    $electronPath = Join-Path $desktopRoot 'node_modules\electron\dist\electron.exe'
    $escapedDesktopRoot = [Regex]::Escape($desktopRoot)

    Get-Process -Name 'electron' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $electronPath } |
        Stop-Process -Force -ErrorAction SilentlyContinue

    try {
        Get-CimInstance Win32_Process |
            Where-Object {
                ($_.CommandLine -match $escapedDesktopRoot -and
                    ($_.CommandLine -match 'vite|npm-cli\.js run dev|npx-cli\.js electron|electron\\cli\.js')) -or
                ($_.CommandLine -match 'summer_camp_agent\.workbench_server')
            } |
            ForEach-Object {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
    } catch {
    }

    Stop-PortOwner -Port 5178
    Stop-PortOwner -Port 8765
}

if (-not (Test-Path -LiteralPath $desktopRoot)) {
    throw "Electron desktop directory was not found: $desktopRoot"
}

if (-not (Test-Path -LiteralPath (Join-Path $desktopRoot 'node_modules'))) {
    throw "Electron dependencies are missing. Run: cd desktop; npm.cmd install"
}

New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot 'data') | Out-Null
Stop-DesktopProcesses

$env:ELECTRON_RENDERER_URL = 'http://127.0.0.1:5178'
$env:SUMMER_CAMP_AGENT_PYTHON = 'python'

& npm.cmd --prefix $desktopRoot run build:main

Start-Process -FilePath 'npm.cmd' `
    -ArgumentList @('run', 'dev', '--', '--port', '5178', '--strictPort') `
    -WorkingDirectory $desktopRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $viteOutLog `
    -RedirectStandardError $viteErrLog | Out-Null

$deadline = (Get-Date).AddSeconds(12)
while (-not (Test-LocalPortListening -Port 5178)) {
    if ((Get-Date) -gt $deadline) {
        throw "Vite desktop renderer did not start on http://127.0.0.1:5178. See: $viteErrLog"
    }
    Start-Sleep -Milliseconds 200
}

Start-Process -FilePath 'npx.cmd' `
    -ArgumentList @('electron', '.') `
    -WorkingDirectory $desktopRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $desktopOutLog `
    -RedirectStandardError $desktopErrLog | Out-Null

Write-Host "[Desktop] Electron desktop app started. Logs: $desktopOutLog / $desktopErrLog"
