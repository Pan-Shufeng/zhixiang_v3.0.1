"""Start the bundled DSH browser with the Zhixiang MCP bridge and shared data."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packaging"))
from server import Settings  # noqa: E402
from launcher import health, is_app, read_state, owned, start, startup_lock  # noqa: E402


def main():
    node = ROOT / "runtime" / "node" / "node.exe"
    python = ROOT / "runtime" / "python.exe"
    cli = ROOT / "dsh" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    patch = ROOT / "dsh" / "zhixiang.patch.yml"
    for file in (node, python, cli, patch, ROOT / "backend" / "mcp_server.py"):
        if not file.is_file():
            raise RuntimeError("DSH 运行文件不完整，请完整解压体验包。")
    config = Settings(ROOT / "config", fallback=False).config()
    if config.get("provider") != "deepseek" or not config.get("api_key"):
        raise RuntimeError("DSH 对话需要 DeepSeek 试用或个人 Key；请先在知向设置中配置。")
    current = health(8186)
    if not owned(current, read_state(), 8186):
        with startup_lock():
            start(8186, True)
    env = os.environ.copy()
    env.update(DSH_HOME=str(ROOT / "data" / "dsh-home"),
               DEEPSEEK_API_KEY=config["api_key"],
               ZHIXIANG_PYTHON=str(python),
               ZHIXIANG_MCP_SCRIPT=str(ROOT / "backend" / "mcp_server.py"),
               ZHIXIANG_CLIENT="dsh",
               ZHIXIANG_PORT="8186")
    print("正在打开 DSH 对话；它通过 MCP 使用同一份知向资料与判断。", flush=True)
    return subprocess.call([str(node), str(cli), "web", "--patch", str(patch), "--port", "3180"], cwd=ROOT / "dsh", env=env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as error:
        print("未能打开 DSH：" + str(error), file=sys.stderr)
        raise SystemExit(1)
