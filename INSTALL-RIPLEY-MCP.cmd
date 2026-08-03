@echo off
setlocal
title Ripley MCP Setup for Codex

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-codex-mcp.ps1"
set "setup_exit=%ERRORLEVEL%"

echo.
if "%setup_exit%"=="0" (
  echo Setup finished. You can close this window.
) else (
  echo Setup did not finish. Take a screenshot of this window and send it to Thomas.
)
echo.
pause
exit /b %setup_exit%
