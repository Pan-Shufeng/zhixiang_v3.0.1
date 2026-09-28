@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo 请先完整解压体验包。
  pause
  exit /b 1
)
"runtime\python.exe" -X utf8 "packaging\launch_dsh.py"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%
