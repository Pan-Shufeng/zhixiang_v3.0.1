"""Portable local-only launcher. Never terminates a process by PID or image name."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "zhixiang-web"
STATE_DIR = ROOT / "data" / ".launcher"
STATE_FILE = STATE_DIR / "instance.json"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def say(message):
    print(message, flush=True)


def request(port, endpoint, body=None, timeout=1.5):
    url = f"http://127.0.0.1:{port}{endpoint}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"})
    with OPENER.open(req, timeout=timeout) as response:
        return json.loads(response.read(100_000).decode("utf-8"))


def health(port):
    try:
        return request(port, "/api/health")
    except (OSError, ValueError, urllib.error.URLError):
        return None


def is_app(value):
    return isinstance(value, dict) and value.get("ok") is True and value.get("app_id") == APP_ID and isinstance(value.get("process_id"), int)


def read_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def owned(value, state, port):
    return is_app(value) and state.get("process_id") == value["process_id"] and state.get("port") == port and state.get("root") == str(ROOT) and bool(state.get("token"))


@contextlib.contextmanager
def startup_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = (STATE_DIR / "operation.lock").open("a+b")
    lock.seek(0)
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    if os.name == "nt":
        import msvcrt
        locked = False
        for _ in range(30):
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
                break
            except OSError:
                time.sleep(0.2)
        if not locked:
            lock.close()
            raise RuntimeError("另一个知向启动或停止操作正在进行，请稍后再试。")
    try:
        yield
    finally:
        if os.name == "nt":
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


def open_page(port, no_browser):
    if not no_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")


def start(port, no_browser):
    previous = read_state()
    previous_port = previous.get("port")
    if isinstance(previous_port, int) and previous_port != port and owned(health(previous_port), previous, previous_port):
        raise RuntimeError(f"当前文件夹已在端口 {previous_port} 运行；请先用同一端口停止，避免重复打开。")
    existing = health(port)
    if is_app(existing):
        state = read_state()
        if not owned(existing, state, port):
            raise RuntimeError("该端口已有另一份知向运行。请从那份文件夹停止后，再打开本体验包。")
        say("知向已经在运行，打开已有页面。")
        open_page(port, no_browser)
        return
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"端口 {port} 正被其他服务使用；知向没有修改或停止它。请关闭冲突服务后重试。")
    server = ROOT / "backend" / "server.py"
    if not server.is_file() or not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise RuntimeError("体验包文件不完整。请先完整解压后，再双击启动文件。")
    runtime = ROOT / "runtime" / "python.exe"
    if not runtime.exists():
        runtime = ROOT / "packaging" / "runtime" / "python.exe"
    if not runtime.exists():
        raise RuntimeError("缺少内置运行环境，请重新解压完整体验包。")
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    (ROOT / "config").mkdir(exist_ok=True)
    token = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env["ZHIXIANG_SHUTDOWN_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [str(runtime), "-X", "utf8", str(server), "--port", str(port), "--no-browser", "--data-dir", str(ROOT / "data"), "--config-dir", str(ROOT / "config")]
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    say("正在打开知向联网版，等待本地服务就绪……")
    with (logs / "server.log").open("ab") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags, close_fds=True)
    state = {"app_id": APP_ID, "process_id": process.pid, "port": port, "root": str(ROOT), "token": token, "started_at": time.time()}
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            STATE_FILE.unlink(missing_ok=True)
            raise RuntimeError("知向没有成功启动。请查看 logs/server.log，或将不含个人配置的日志交给作者。")
        current = health(port)
        if owned(current, state, port):
            say(f"知向联网版已就绪：http://127.0.0.1:{port}")
            open_page(port, no_browser)
            return
        time.sleep(0.5)
    # A slow/unhealthy child is not announced as ready. Leave a record for diagnosis;
    # never kill by port/PID and accidentally affect another service.
    raise RuntimeError("等待服务就绪超时，尚未确认启动成功。请查看 logs/server.log；不要重复开启多份体验包。")


def stop(port):
    current = health(port)
    if current is None:
        say("没有检测到正在运行的知向服务。")
        return
    state = read_state()
    if not owned(current, state, port):
        raise RuntimeError("此端口不是由当前文件夹启动的知向；未停止任何服务。")
    request(port, "/api/shutdown", {"token": state["token"]}, timeout=3)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        time.sleep(0.25)
        if not owned(health(port), state, port):
            STATE_FILE.unlink(missing_ok=True)
            say("知向已停止。已保存的判断仍保留在本文件夹中。")
            return
    raise RuntimeError("已发出停止请求，但尚未确认退出；未强制结束任何进程。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--port", type=int, default=8186)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "status":
            current = health(args.port)
            say("知向正在运行。" if owned(current, read_state(), args.port) else "当前文件夹的知向未运行。")
            return 0
        with startup_lock():
            if args.action == "start":
                start(args.port, args.no_browser)
            else:
                stop(args.port)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        say(f"未完成：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
