@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "ZHIXIANG_ROOT=%~dp0"
set "ZHIXIANG_PY=%ZHIXIANG_ROOT%runtime\python.exe"
if not exist "%ZHIXIANG_PY%" set "ZHIXIANG_PY=%ZHIXIANG_ROOT%packaging\runtime\python.exe"
if not exist "%ZHIXIANG_PY%" (
  echo Missing bundled runtime. Please extract the full ZIP first.
  pause
  exit /b 1
)
"%ZHIXIANG_PY%" -X utf8 "%ZHIXIANG_ROOT%packaging\launcher.py" stop %*
set "ZHIXIANG_EXIT=%ERRORLEVEL%"
if not "%ZHIXIANG_EXIT%"=="0" pause
exit /b %ZHIXIANG_EXIT%