@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_startup.ps1"
if errorlevel 1 (
  echo.
  echo Startup installation failed.
  pause
  exit /b 1
)
echo.
pause
