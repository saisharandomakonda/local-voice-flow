@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo App is not installed. Run setup.bat first.
  pause
  exit /b 1
)

if not exist ".env" (
  echo Configuration is missing. Copy .env.example to .env and add your API key.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" app.py
