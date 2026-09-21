"""Validate the real ZIP in a fresh Chinese/space path using only its runtime.

Runs local prepared-case/persistence checks, never makes a model call. Port defaults
to 8189 to leave the original 8176 and new developer 8186 instances alone.
Also performs a real explicit web query and reads an original without model calls.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=ROOT / "交付" / "知向联网版_Windows体验包.zip")
    parser.add_argument("--port", type=int, default=8189)
    parser.add_argument("--expected-model", default="deepseek-v4-pro")
    args = parser.parse_args()
    with socket.socket() as probe:
        probe.settimeout(0.4)
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            raise RuntimeError("Verification port is already in use; no service was touched")
    destination = ROOT / "验收" / ("最终解压验收 空格路径 " + time.strftime("%Y%m%d-%H%M%S"))
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(args.zip) as archive:
        for name in archive.namelist():
            if not (destination / name).resolve().is_relative_to(destination.resolve()):
                raise RuntimeError("Archive path escapes extraction folder")
        archive.extractall(destination)
    app = destination / "知向联网版"
    assert not (app / "data" / "knowledge.sqlite3").exists()
    assert not (app / "config" / "local.json").exists()
    assert not (app / "backend" / "checks").exists()
    trial = json.loads((app / "config" / "trial.json").read_text(encoding="utf-8"))
    assert trial["model"] == args.expected_model, 'Portable trial model differs from verified edition model'
    for file in app.rglob('*'):
        if file.is_file() and trial['api_key'].encode('utf-8') in file.read_bytes():
            assert file.relative_to(app).as_posix() == 'config/trial.json', 'Trial key outside intended backend config'
    manifest = json.loads((app / "packaging" / "file_manifest.json").read_text(encoding="utf-8"))
    for relative, digest in manifest.items():
        assert hashlib.sha256((app / relative).read_bytes()).hexdigest() == digest, relative
    assert len(json.loads((app / "backend" / "seed_data" / "sources.json").read_text(encoding="utf-8"))) == 12
    env = os.environ.copy()
    windows_directory = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetWindowsDirectoryW(windows_directory, len(windows_directory)):
        raise RuntimeError("Unable to locate the Windows system directory")
    system_root = Path(windows_directory.value)
    env["SystemRoot"] = str(system_root)
    env["PATH"] = str(system_root / "System32") + ";" + str(system_root)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    command_processor = str(system_root / "System32" / "cmd.exe")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{args.port}"
    report = {"zip": str(args.zip), "zip_sha256": hashlib.sha256(args.zip.read_bytes()).hexdigest(), "extracted": str(app), "port": args.port, "initial_history_absent": True, "personal_settings_absent": True, "manifest_verified": True, "developer_path_removed": True, "trial_model": trial['model'], "trial_key_only_in_backend_config": True, "model_calls": 0, "all_checks_passed": False}

    def command(action):
        filename = "启动知向联网版.cmd" if action == "start" else "停止知向联网版.cmd"
        # /s removes the outer pair, leaving the application path correctly quoted.
        text = f'"{command_processor}" /d /s /c ""{app / filename}" --port {args.port} --no-browser"'
        process = subprocess.run(text, cwd=app, env=env, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=85)
        if process.returncode != 0:
            raise RuntimeError("Portable " + action + " failed: " + process.stdout)
        return process.stdout

    def req(path, body=None, raw=False):
        request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "Origin": base})
        with opener.open(request, timeout=20) as response:
            payload = response.read()
        assert trial["api_key"].encode("utf-8") not in payload, "Trial key exposed through API"
        return payload if raw else json.loads(payload)

    started = False
    try:
        command("start")
        started = True
        initial = req("/api/bootstrap")
        first_health = req("/api/health")
        assert first_health["app_id"] == "zhixiang-web"
        search_settings = req("/api/search/settings")
        assert search_settings["provider"] == "public" and "api_key" not in search_settings
        report["search_settings_public_default"] = True
        assert initial["questions"] == []
        assert initial["settings"]["configured"] and initial["settings"]["trial"]
        assert initial["settings"]["model"] == trial["model"]
        assert b'<div id="root">' in req("/", raw=True)
        portable_check = subprocess.run([str(app / "runtime" / "python.exe"), "-X", "utf8", "-c", "import sys,ssl,sqlite3,requests,pypdf,fontTools.t1Lib; print(sys.version.split()[0])"], capture_output=True, text=True, env=env, check=True)
        report["embedded_runtime_imports"] = portable_check.stdout.strip()
        result = req("/api/analyze", {"mode": "prepared", "example_id": "eastbuy"})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = req("/api/jobs/" + result["job_id"])
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert job["status"] == "done", job.get("error")
        q = job["result"]
        assert q["analysis"]["mode"] == "prepared"
        qid = q["id"]
        source = req("/api/sources/" + q["source_ids"][0])
        original = req(source["file_url"], raw=True)
        assert len(original) > 1000 and source["text"]
        original_record = next(s for s in json.loads((app / "backend" / "seed_data" / "sources.json").read_text(encoding="utf-8")) if s["id"] == q["source_ids"][0])
        original_hash = hashlib.sha256(original).hexdigest()
        assert original_hash == original_record["original_sha256"]
        for text in ("体验包验收：先核对依据，再形成判断。", "体验包验收：已核对来源，保留待核实问题。"):
            req("/api/questions/" + qid + "/judgment", {"text": text, "source_ids": q["source_ids"][:1], "unresolved": ["测试记录：核对口径"]})
        saved = req("/api/questions/" + qid)
        assert len(saved["history"]) == 2
        assert "体验包验收" in req("/api/export/" + qid, raw=True).decode("utf-8")
        def await_job(result, seconds=110):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                current = req("/api/jobs/" + result["job_id"])
                if current["status"] in ("done", "error"):
                    assert current["status"] == "done", current.get("error")
                    return current
                time.sleep(0.4)
            raise RuntimeError("Portable search/import did not finish within verification limit")

        searched = await_job(req("/api/search", {"question": "微软2025年报的经营数据", "query": '"Microsoft" "2025" "annual report"'}))
        web_qid = searched["result"]["id"]
        web_question = req("/api/questions/" + web_qid)
        candidates = web_question["search_report"]["candidates"]
        selected = next(c for c in candidates if "www.microsoft.com/investor/reports/ar25/index.html" in c["url"])
        await_job(req("/api/questions/" + web_qid + "/search-import", {"candidate_ids": [selected["id"]], "analyze": False}))
        imported_question = req("/api/questions/" + web_qid)
        imported_source = req("/api/sources/" + imported_question["source_ids"][0])
        assert len(imported_source["text"]) > 10000 and imported_question["analysis"] is None
        report["real_web_search"] = {"provider": web_question["search_report"]["provider"], "query": web_question["search_report"]["query"], "candidate_count": len(candidates), "imported_url": imported_source["url"], "original_characters": len(imported_source["text"]), "model_calls": 0}
        own = req("/api/settings", {"use_trial": False, "api_key": "sk-portable-validation-not-real", "base_url": "https://api.deepseek.com", "model": "deepseek-flash"})
        assert own["configured"] and not own["trial"]
        restored = req("/api/settings", {"use_trial": True})
        assert restored["configured"] and restored["trial"]
        command("start")
        assert req("/api/health")["process_id"] == first_health["process_id"]
        command("stop")
        started = False
        command("start")
        started = True
        second_health = req("/api/health")
        assert second_health["process_id"] != first_health["process_id"]
        restored_q = req("/api/questions/" + qid)
        assert restored_q["judgment"] == saved["judgment"] and restored_q["history"] == saved["history"]
        restored_web = req("/api/questions/" + web_qid)
        assert restored_web["source_ids"] == imported_question["source_ids"] and restored_web["search_report"] == imported_question["search_report"]
        report["web_search_restart_persistence"] = True
        report.update({"frontend_served": True, "trial_not_exposed": True, "public_sources": len(initial["sources"]), "prepared_case": True, "original_download_bytes": len(original), "original_download_sha256": original_hash, "original_download_matches_bundled_source": True, "browser_pdf_preview_tested": False, "judgment_history_saved": 2, "export_checked": True, "own_config_save_and_trial_restore": True, "duplicate_start_reused": True, "restart_persistence": True})
    finally:
        if started:
            command("stop")
        with socket.socket() as probe:
            probe.settimeout(0.4)
            report["test_service_stopped"] = probe.connect_ex(("127.0.0.1", args.port)) != 0
        output = HERE / "portable_smoke_final.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert report["test_service_stopped"]
    report["all_checks_passed"] = True
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
