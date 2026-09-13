@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" python -m venv .venv
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo Setup complete. Add your OpenAI API key to .env, then run run.bat.
pause
exit /b 0

:error
echo.
echo Setup failed.
pause
exit /b 1
