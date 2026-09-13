@echo off
setlocal
set "SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Local Voice Flow.lnk"
if exist "%SHORTCUT%" del "%SHORTCUT%"
echo Local Voice Flow was removed from Windows startup.
pause
