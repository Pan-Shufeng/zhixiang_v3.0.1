@echo off
setlocal
cd /d "%~dp0"
"runtime\python.exe" -X utf8 "packaging\launcher.py" start --no-browser
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8186/#connections"
