@echo off
rem Double-click to start karaoke. Opens the TV page on the second screen and the control page on this one.
rem Close this window to stop the app. Starting again restarts it cleanly.
rem To turn on the v1 import page, set KARAOKE_V1 to the v1 install folder before starting.

title Karaoke - close this window to stop
cd /d "%~dp0server"
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
set "PYTHONIOENCODING=utf-8"

where uv >nul 2>nul || (
  echo uv was not found. Install it from https://docs.astral.sh/uv/ and try again.
  pause
  exit /b 1
)

echo Stopping any karaoke already running...
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -match 'karaoke(\.exe)?\W+serve') -or ($_.Name -eq 'msedge.exe' -and $_.CommandLine -match 'Karaoke\\edge-(tv|control)') } | Where-Object { $_.ProcessId -ne $PID } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"

if not exist "..\web\dist\index.html" (
  echo Building the web pages for the first time...
  pushd "..\web"
  call npm install || goto :failed
  call npm run build || goto :failed
  popd
)

set "V1_ARGS="
if defined KARAOKE_V1 set "V1_ARGS=--v1 "%KARAOKE_V1%""

echo Starting karaoke...
uv run karaoke serve %V1_ARGS%
echo.
echo Karaoke stopped.
pause
exit /b 0

:failed
echo Building the web pages failed. See the messages above.
pause
exit /b 1
