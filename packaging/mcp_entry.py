"""Start this copy of Zhixiang on demand, then serve MCP over clean stdio."""
import argparse
import contextlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))
from launcher import health, owned, read_state, start, startup_lock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", choices=["codex", "workbuddy", "dsh", "other", "diagnostic"], default="other")
    parser.add_argument("--port", type=int, default=8186)
    args = parser.parse_args()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if not owned(health(args.port), read_state(), args.port):
                with startup_lock():
                    start(args.port, True)
        env = os.environ.copy()
        env.update(ZHIXIANG_PORT=str(args.port), ZHIXIANG_CLIENT=args.client, PYTHONIOENCODING="utf-8")
        return subprocess.call([sys.executable, "-X", "utf8", str(ROOT / "backend" / "mcp_server.py")], cwd=ROOT, env=env)
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
