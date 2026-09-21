@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo 请先解压完整的知向联网版体验包。
  pause
  exit /b 1
)
echo MCP服务将通过标准输入输出等待AI客户端连接。
echo 请先启动“启动知向联网版.cmd”，再由AI客户端启动本文件。
"runtime\python.exe" "backend\mcp_server.py"
