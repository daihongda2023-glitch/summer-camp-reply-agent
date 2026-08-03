@echo off
setlocal
chcp 65001 >nul

set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "REPO_ROOT_B64=RDpcd29ya3NwYWNlMVxzdW1tZXItY2FtcC1yZXBseS1hZ2VudA=="
set "BOOTSTRAP_LOG=%TEMP%\summer_camp_agent_launcher_bootstrap_%RANDOM%.log"

> "%BOOTSTRAP_LOG%" echo Launching summer camp Agent launcher...
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $repo=[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%REPO_ROOT_B64%')); $launcher=Join-Path $repo 'scripts\start_agent_workbench.ps1'; if (!(Test-Path -LiteralPath $launcher)) { throw ('Agent launcher script was not found: ' + $launcher) }; Start-Process -FilePath '%POWERSHELL_EXE%' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$launcher) -WindowStyle Hidden; Write-Host ('Started Agent launcher: ' + $launcher)" >> "%BOOTSTRAP_LOG%" 2>&1
set "EXIT_CODE=%errorlevel%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Summer camp Agent failed to start. Launcher log:
  if exist "%BOOTSTRAP_LOG%" type "%BOOTSTRAP_LOG%"
  "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "$repo=[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%REPO_ROOT_B64%')); $log=Join-Path (Join-Path $repo 'data') 'agent_launcher.log'; Write-Host $log; if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 80 }"
  pause
  exit /b %EXIT_CODE%
)
