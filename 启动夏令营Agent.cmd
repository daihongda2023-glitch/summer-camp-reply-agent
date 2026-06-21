@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw -m summer_camp_agent.gui
) else (
  start "" python -m summer_camp_agent.gui
)
