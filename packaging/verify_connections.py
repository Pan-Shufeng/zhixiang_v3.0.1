"""Verify the released connector ZIP without modifying the real user's client settings."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
PORT = 8196


def main():
    archive = ROOT / "交付/知向_多客户端连接版_Windows体验包.zip"
    folder = ROOT / "验收" / ("连接版 中文 空格 " + time.strftime("%Y%m%d-%H%M%S"))
    folder.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.namelist():
            assert (folder / item).resolve().is_relative_to(folder.resolve())
        z.extractall(folder)
    app = folder / "知向_DSH集成版"
    profile = folder / "test-user-profile"
    for directory in (".codex", ".workbuddy"):
        (profile / directory).mkdir(parents=True)
    (profile / ".codex/config.toml").write_text('# existing preference\nmodel="example"\n[mcp_servers.other]\ncommand="other"\n', encoding="utf-8")
    (profile / ".workbuddy/mcp.json").write_text('{"mcpServers":{"other":{"command":"other"}},"preference":true}', encoding="utf-8")
    manifest = json.loads((app / "packaging/file_manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest.items():
        assert hashlib.sha256((app / name).read_bytes()).hexdigest() == digest, name
    assert not (app / "data/knowledge.sqlite3").exists()
    env = os.environ.copy()
    env["USERPROFILE"] = str(profile)
    env.pop("CODEX_HOME", None)
    python = str(app / "runtime/python.exe")
    frames = [
        {"jsonrpc":"2.0", "id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"acceptance-diagnostic","version":"1"},"capabilities":{}}},
        {"jsonrpc":"2.0","method":"notifications/initialized"},
        {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},
        {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"zhixiang_open_workspace","arguments":{}}},
        {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"zhixiang_list_questions","arguments":{}}},
    ]
    run = subprocess.run([python, "-X", "utf8", str(app / "packaging/mcp_entry.py"), "--client", "diagnostic", "--port", str(PORT)], env=env, input="\n".join(json.dumps(f) for f in frames)+"\n", encoding="utf-8", capture_output=True, timeout=100)
    assert run.returncode == 0, run.stderr[-500:]
    responses = [json.loads(line) for line in run.stdout.splitlines()]
    assert [r["id"] for r in responses] == [1,2,3,4]
    assert len(responses[1]["result"]["tools"]) == 10
    assert not responses[2]["result"]["isError"] and not responses[3]["result"]["isError"]
    base = f"http://127.0.0.1:{PORT}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, payload=None):
        req = urllib.request.Request(base+path, data=None if payload is None else json.dumps(payload).encode(), headers={"Content-Type":"application/json","Origin":base})
        with opener.open(req, timeout=30) as response:
            return json.load(response)

    assert request("/api/health")["version"] == "3.1.1-connect"
    assert request("/api/connections")["events"] == {}
    for client, file in (("codex", profile / ".codex/config.toml"), ("workbuddy", profile / ".workbuddy/mcp.json")):
        added = request("/api/connections/install", {"client":client})
        assert Path(added["backup"]).is_file()
        assert str(profile) in added["path"]
        content = file.read_text(encoding="utf-8")
        parsed = tomllib.loads(content) if client == "codex" else json.loads(content)
        key = "mcp_servers" if client == "codex" else "mcpServers"
        assert "other" in parsed[key] and "zhixiang" in parsed[key]
        request("/api/connections/remove", {"client":client})
        content = file.read_text(encoding="utf-8")
        parsed = tomllib.loads(content) if client == "codex" else json.loads(content)
        assert set(parsed[key]) == {"other"}
    generated = request("/api/connections/dsh-patch", {})
    assert Path(generated["path"]).is_file()
    report = {"zip": str(archive), "sha256":hashlib.sha256(archive.read_bytes()).hexdigest(), "app":str(app), "profile":str(profile), "port":PORT, "manifest_verified":len(manifest), "cold_start_mcp_tools":10, "real_tool_calls":["zhixiang_open_workspace","zhixiang_list_questions"], "codex_workbuddy_install_remove_preserves_other_config":True, "diagnostic_not_marked_as_client_success":True, "dsh_patch":generated["path"], "service_left_running_for_ui_validation":True}
    (ROOT / "验收/连接版验收.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))


if __name__ == "__main__":
    main()
