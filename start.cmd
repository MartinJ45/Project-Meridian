@echo off
rem Windows launcher: works from cmd, PowerShell, or double-click.
rem Runs start.ps1 without needing to change the PowerShell execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
