@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo 请先解压完整的知向体验包。 1>&2
  exit /b 1
)
"runtime\python.exe" -X utf8 "packaging\mcp_entry.py" --client other
