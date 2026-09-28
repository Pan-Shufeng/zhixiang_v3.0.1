"""Local client onboarding. Never replace another server or a user's DSH profile."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import tomllib
import uuid

ROOT = Path(__file__).resolve().parent.parent
LOCK = threading.RLock()
EVENT_LOCK = threading.RLock()
BEGIN = "# BEGIN ZHIXIANG CONNECTION"
END = "# END ZHIXIANG CONNECTION"
CLIENTS = ("codex", "workbuddy", "dsh")


def runtime(root=ROOT):
    for path in (root / "runtime/python.exe", root / "packaging/runtime/python.exe"):
        if path.is_file():
            return str(path)
    return sys.executable


def entry(client, port=8186, root=ROOT):
    return {"command": runtime(root), "args": ["-X", "utf8", str(root / "packaging/mcp_entry.py"), "--client", client, "--port", str(port)]}


def config_path(client, home=None):
    home = Path(home) if home else Path.home()
    if client == "codex":
        return home / ".codex/config.toml"
    if client == "workbuddy":
        return home / ".workbuddy/mcp.json"
    raise ValueError("请选择 Codex 或 WorkBuddy。")


def codex_path(home=None):
    return Path(os.environ["CODEX_HOME"]) / "config.toml" if home is None and os.environ.get("CODEX_HOME") else config_path("codex", home)


def target(client, home=None):
    return codex_path(home) if client == "codex" else config_path(client, home)


def read_config(client, path):
    raw = path.read_bytes() if path.exists() else b""
    text = raw.decode("utf-8-sig")
    try:
        parsed = tomllib.loads(text) if client == "codex" else json.loads(text or "{}")
        key = "mcp_servers" if client == "codex" else "mcpServers"
        if not isinstance(parsed, dict) or not isinstance(parsed.get(key, {}), dict):
            raise ValueError()
        return raw, text, parsed, key
    except (ValueError, TypeError):
        raise ValueError("客户端配置格式暂时无法识别，未修改。请先在客户端修复配置，或使用下方手动配置。") from None


def block(config):
    return BEGIN + "\n[mcp_servers.zhixiang]\ncommand = " + json.dumps(config["command"], ensure_ascii=False) + "\nargs = " + json.dumps(config["args"], ensure_ascii=False) + "\nstartup_timeout_sec = 90\ntool_timeout_sec = 180\n" + END + "\n"


def write_back(path, before, after):
    path.parent.mkdir(parents=True, exist_ok=True)
    if (path.read_bytes() if path.exists() else b"") != before:
        raise ValueError("客户端配置刚刚发生变化，请刷新后重试。")
    backup = path.with_name(path.name + ".zhixiang-backup-" + uuid.uuid4().hex[:10])
    if before:
        backup.write_bytes(before)
    temp = path.with_name(path.name + ".zhixiang-" + uuid.uuid4().hex)
    temp.write_bytes(after)
    if (path.read_bytes() if path.exists() else b"") != before:
        temp.unlink(missing_ok=True)
        raise ValueError("客户端配置刚刚发生变化，请刷新后重试。")
    os.replace(temp, path)
    return str(backup) if before else None


def configure(client, remove=False, home=None, port=8186, root=ROOT):
    with LOCK:
        path = target(client, home)
        raw, text, parsed, key = read_config(client, path)
        expected = entry(client, port, root)
        existing = parsed.get(key, {}).get("zhixiang")
        if existing is not None and not isinstance(existing, dict):
            raise ValueError("zhixiang 配置格式无法识别，未修改。请先在客户端核对。")
        if existing and (existing.get("command") != expected["command"] or existing.get("args") != expected["args"]):
            raise ValueError("这个客户端已连接另一份知向。为保留原资料，请先从原来的知向移除连接，或手动核对配置。")
        if remove and not existing:
            return {"message": "这个客户端没有本知向连接，无需移除。"}
        if not remove and existing:
            return {"message": "配置已存在；请在客户端新开对话并试用知向工具。"}
        if client == "codex":
            if remove:
                expected_block = block(expected)
                if text.count(expected_block) != 1:
                    raise ValueError("知向配置已被手动修改，未自动删除。请在 Codex 设置中移除 zhixiang。")
                updated = text.replace(expected_block, "", 1)
            else:
                if BEGIN in text or END in text:
                    raise ValueError("检测到旧的连接标记，请先手动核对 Codex 配置。")
                updated = text + ("\n" if text and not text.endswith("\n") else "") + "\n" + block(expected)
            tomllib.loads(updated)
        else:
            servers = parsed.setdefault(key, {})
            if remove:
                del servers["zhixiang"]
            else:
                servers["zhixiang"] = expected
            updated = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
        backup = write_back(path, raw, updated.encode("utf-8"))
        return {"message": "已移除本知向连接，其他配置保留。请重启客户端。" if remove else "配置已加入，请在客户端重启连接或新开对话，再发送下方试用语句。", "backup": backup, "path": str(path)}


def dsh_binary():
    return shutil.which("dsh.cmd") or shutil.which("dsh")


def dsh_patch(port=8186, root=ROOT):
    config = entry("dsh", port, root)
    # JSON is a YAML subset, preserving Windows paths without executable YAML tags.
    patch = [{"insert": [{"id": "zhixiang-mcp", "name": "@deepseek-ai/dsh-mcp-client", "config": {"serverName": "zhixiang", "transport": "stdio", **config, "toolCallTimeoutMs": 180000, "failOnStartupError": True}}]}]
    path = root / "data/connections/dsh-zhixiang.patch.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def status(port=8186, root=ROOT, home=None):
    clients = []
    for client in ("codex", "workbuddy"):
        path = target(client, home)
        try:
            _, _, parsed, key = read_config(client, path)
            present = parsed.get(key, {}).get("zhixiang")
            if present is not None and not isinstance(present, dict):
                raise ValueError("Invalid server entry")
            ours = present and present.get("command") == entry(client, port, root)["command"] and present.get("args") == entry(client, port, root)["args"]
            state = "configured" if ours else "conflict" if present else "not_configured"
        except (OSError, ValueError):
            state = "unreadable"
        clients.append({"id": client, "path": str(path), "state": state})
    clients.append({"id": "dsh", "state": "available" if dsh_binary() else "not_found", "path": dsh_binary()})
    return {"clients": clients, "web_url": f"http://127.0.0.1:{port}/", "events": read_events(root), "manual": {"codex": block(entry("codex", port, root)), "workbuddy": json.dumps({"mcpServers": {"zhixiang": entry("workbuddy", port, root)}}, ensure_ascii=False, indent=2)}}


def read_events(root=ROOT):
    try:
        return json.loads((root / "data/connections/events.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_event(payload, root=ROOT):
    client = payload.get("client")
    if client not in CLIENTS or payload.get("stage") not in ("initialized", "tool_called"):
        return {"ok": True}
    # DSH startup waits for MCP initialize; its event must not wait on the launch lock.
    with EVENT_LOCK:
        events = read_events(root)
        previous = events.get(client, {})
        event = {"at": datetime.now(timezone.utc).isoformat(), "client_name": str(payload.get("client_name", ""))[:80], "stage": payload["stage"], "tool": str(payload.get("tool", ""))[:80]}
        if payload["stage"] == "tool_called":
            event["last_tool_at"] = event["at"]
        elif previous.get("last_tool_at"):
            event["last_tool_at"] = previous["last_tool_at"]
        events[client] = event
        path = root / "data/connections/events.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


def launch_existing_dsh(port=8186, root=ROOT):
    with LOCK:
        return _launch_existing_dsh(port, root)


def _launch_existing_dsh(port, root):
    binary = dsh_binary()
    if not binary:
        raise ValueError("未在系统命令路径找到 DSH。请从已安装 DSH 的终端运行下方连接命令，或使用包内的启动DSH对话.cmd。")
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", 3181)) == 0:
            raise ValueError("3181 端口已有服务，请先查看已打开的 DSH 页面；本次没有重复启动。")
    patch = dsh_patch(port, root)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    (root / "logs").mkdir(exist_ok=True)
    log_path = root / "logs/existing-dsh.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen([binary, "web", "--patch", str(patch), "--port", "3181", "--no-open"], cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError("DSH 启动未完成，请检查 logs/existing-dsh.log；现有配置未修改。")
        # DSH announces this process-specific URL once its web loader is ready.
        # Only a strict loopback URL is returned to our same-origin local page.
        match = re.search(r"dsh web: (http://127\.0\.0\.1:3181/[^\s]*)", log_path.read_text(encoding="utf-8", errors="replace"))
        if match:
            return {"message": "DSH 网页已启动。点击下方入口，再发送试用语句；工具调用成功后，这里才会出现记录。", "url": match.group(1), "process_id": process.pid}
        time.sleep(0.25)
    return {"message": "已发出启动请求，但尚未确认网页就绪。请查看 logs/existing-dsh.log 中本次生成的本机地址。", "process_id": process.pid}
