@echo off
rem The installed app's launcher (the Start menu shortcut runs this). The developer's copy uses Start Karaoke.cmd.
rem First start: installs Python and the locked packages into %LOCALAPPDATA%\Karaoke\runtime (1-3 GB, once).
rem When the app exits to upgrade, this runs the downloaded installer through upgrade.ps1 and the new version starts.

title Karaoke - close this window to stop
setlocal
set "APP=%~dp0"
set "RUNTIME=%LOCALAPPDATA%\Karaoke\runtime"
set "PATH=%APP%bin;%RUNTIME%\tools-bin;%PATH%"
set "UV_PYTHON_INSTALL_DIR=%RUNTIME%\python"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_PROJECT_ENVIRONMENT=%RUNTIME%\venv"
set "UV_TOOL_DIR=%RUNTIME%\tools"
set "UV_TOOL_BIN_DIR=%RUNTIME%\tools-bin"
set "UV_CACHE_DIR=%RUNTIME%\cache"
set "PYTHONIOENCODING=utf-8"

echo Stopping any karaoke already running...
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -match 'karaoke(\.exe)?\W+serve') -or ($_.Name -eq 'msedge.exe' -and $_.CommandLine -match 'Karaoke\\edge-(tv|control)') } | Where-Object { $_.ProcessId -ne $PID } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"

rem An NVIDIA card gets the CUDA build of PyTorch; any other laptop gets the CPU build.
set "TORCH=cpu"
nvidia-smi -L >nul 2>nul && set "TORCH=cu128"
rem For testing: set KARAOKE_TORCH=cpu to try the CPU build on a laptop with an NVIDIA card.
if defined KARAOKE_TORCH set "TORCH=%KARAOKE_TORCH%"

cd /d "%APP%server"
echo.
echo Getting ready (PyTorch build: %TORCH%). The first start downloads 1 to 3 GB and takes a while; later starts take seconds.
uv sync --frozen --no-default-groups --group %TORCH% --reinstall-package karaoke || goto :failed
if not exist "%RUNTIME%\tools-bin\yt-dlp.exe" (
  uv tool install "yt-dlp[default]" || goto :failed
)

echo.
echo Starting karaoke...
"%RUNTIME%\venv\Scripts\karaoke.exe" serve --installed %*
if "%ERRORLEVEL%"=="75" goto :upgrade
echo.
echo Karaoke stopped.
pause
exit /b 0

:upgrade
set "PENDING=%LOCALAPPDATA%\Karaoke\updates\pending.txt"
set "INSTALLER="
set "VERSION="
for /f "usebackq delims=" %%L in ("%PENDING%") do (
  if not defined INSTALLER (set "INSTALLER=%%L") else if not defined VERSION set "VERSION=%%L"
)
del "%PENDING%" >nul 2>nul
copy /y "%APP%upgrade.ps1" "%TEMP%\karaoke-upgrade.ps1" >nul
start "Karaoke upgrade" powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\karaoke-upgrade.ps1" ^
  -Installer "%INSTALLER%" -Version "%VERSION%" -AppDir "%APP:~0,-1%"
exit

:failed
echo.
echo Getting ready failed. Check the internet connection and start Karaoke again.
pause
exit /b 1
