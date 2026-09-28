@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo 请先解压完整的知向体验包。 1>&2
  exit /b 1
)
echo 知向 MCP 已连接标准输入输出；请先启动知向网页服务。 1>&2
"runtime\python.exe" "backend\mcp_server.py"
