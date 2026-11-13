@echo off
rem Double-click to start Claude Code Remote Control in this repo, so you can drive it from your phone or claude.ai.
rem Close this window to stop it.

title Claude remote control - karaoke-app-v2
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where claude >nul 2>nul || (
  echo The claude command was not found. Install it with: irm https://claude.ai/install.ps1 ^| iex
  pause
  exit /b 1
)

call claude remote-control
echo.
echo Remote control stopped.
pause