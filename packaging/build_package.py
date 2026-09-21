"""Create a clean, offline-installable Windows experience ZIP from built assets.

No private databases, personal settings, logs, or source-workspace histories are copied.
The explicitly authorized classroom trial key is read only while building config/trial.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_TRIAL_ENV = Path(r"C:\Users\shufe\.config\ai-course\deepseek.env")
DEFAULT_TRIAL_MODEL = "deepseek-v4-pro"


def load_trial(path):
    fields = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        fields[name.strip()] = value.strip().strip('"').strip("'")
    key = fields.get("DEEPSEEK_API_KEY", "")
    if not key or not key.startswith("sk-"):
        raise RuntimeError("Trial configuration is missing or invalid; no package created.")
    return {
        "api_key": key,
        "base_url": fields.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": fields.get("DEEPSEEK_MODEL", "deepseek-flash"),
        "provider": "deepseek",
    }


def copy_tree(source, destination, extra_ignores=()):
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store", "Thumbs.db", *extra_ignores))


def collect_licenses(stage):
    target = stage / "第三方许可"
    target.mkdir()
    python_license = stage / "runtime" / "LICENSE.txt"
    if not python_license.exists():
        raise RuntimeError("Official Python license missing")
    shutil.copy2(python_license, target / "Python-LICENSE.txt")
    packages = []
    for metadata in sorted((stage / "runtime" / "Lib" / "site-packages").glob("*.dist-info")):
        package_dir = target / metadata.name.replace(".dist-info", "")
        files = [f for f in metadata.rglob("*") if f.is_file() and ("license" in f.name.lower() or f.name.lower().startswith("copying") or f.name.lower() == "notice")]
        for file in files:
            destination = package_dir / file.relative_to(metadata)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
        if not files:
            raise RuntimeError(f"Dependency license missing for {metadata.name}")
        packages.append(metadata.name.replace(".dist-info", ""))
    # Collect only the application's installed production dependency graph.
    frontend = ROOT / "frontend"
    package_json = frontend / "package.json"
    frontend_packages = []
    pending = [(name, frontend) for name in json.loads(package_json.read_text(encoding="utf-8")).get("dependencies", {})] if package_json.exists() else []
    seen = set()
    while pending:
        name, from_dir = pending.pop()
        # Match Node resolution for pnpm's linked, isolated dependency folders.
        module = None
        for ancestor in (from_dir.resolve(), *from_dir.resolve().parents):
            candidate = ancestor / "node_modules" / name
            if (candidate / "package.json").exists():
                module = candidate.resolve()
                break
        if module is None:
            raise RuntimeError(f"Cannot resolve frontend license for {name}")
        if str(module) in seen:
            continue
        seen.add(str(module))
        metadata_file = module / "package.json"
        if not metadata_file.exists():
            raise RuntimeError(f"Cannot verify frontend license for {name}")
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        pending.extend((child, module) for child in metadata.get("dependencies", {}))
        licenses = [f for f in module.iterdir() if f.is_file() and f.name.lower().startswith(("license", "copying", "notice"))]
        if not licenses:
            raise RuntimeError(f"Frontend license missing for {name}")
        destination = target / (name.replace("/", "_").replace("@", "") + "-" + metadata.get("version", "unknown"))
        destination.mkdir(exist_ok=True)
        for file in licenses:
            shutil.copy2(file, destination / file.name)
        frontend_packages.append(f"{name} {metadata.get('version', 'unknown')}")
    notice = """# 第三方软件说明

本体验包内置官方 CPython Windows x64 嵌入式发行版，保留原解释器二进制文件及许可证。
为使应用在独立目录运行，仅调整 python313._pth 搜索路径，并附带应用所需第三方依赖；不改写解释器源码，不修改系统 Python、注册表或 PATH。

Python 来源与许可：
- https://www.python.org/downloads/release/python-31315/
- https://docs.python.org/3.13/license.html
- https://docs.python.org/3.13/using/windows.html#the-embeddable-package

下面各包的完整许可文件存放在本目录。Python 依赖也在 runtime/Lib/site-packages 的 dist-info 目录保留原有元数据与许可。

Python 依赖：
""" + "\n".join(f"- {name}" for name in packages) + "\n\n前端运行依赖：\n" + "\n".join(f"- {name}" for name in frontend_packages) + "\n\n公开案例材料的权利属于原发布者；材料的用途、出处和边界以应用中的来源说明为准。\n"
    (target / "说明.md").write_text(notice, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial-env", type=Path, default=DEFAULT_TRIAL_ENV)
    parser.add_argument("--trial-model", default=DEFAULT_TRIAL_MODEL, help="Model verified for this independent web edition; does not edit the shared env file")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "交付")
    args = parser.parse_args()
    requirements = [ROOT / "backend" / "server.py", ROOT / "backend" / "seed_data" / "sources.json", ROOT / "frontend" / "dist" / "index.html", HERE / "runtime" / "python.exe", HERE / "runtime_manifest.json"]
    if any(not p.is_file() for p in requirements):
        raise RuntimeError("Frontend, backend or vendored runtime is not ready; package build stopped.")
    trial = load_trial(args.trial_env)
    trial["model"] = args.trial_model
    build_root = (HERE / "builds" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])).resolve()
    if not build_root.is_relative_to(HERE.resolve()):
        raise RuntimeError("Unexpected build destination")
    stage = build_root / "知向联网版"
    stage.mkdir(parents=True)
    backend_dir = stage / "backend"
    backend_dir.mkdir()
    for source in (ROOT / "backend").iterdir():
        if source.is_file() and (source.suffix == ".py" or source.name in ("requirements.txt", "LICENSE", "LICENSE.txt")) and not source.name.startswith(("test", "build_", "check_", "probe_", "diagnose_")):
            shutil.copy2(source, backend_dir / source.name)
    copy_tree(ROOT / "backend" / "seed_data", backend_dir / "seed_data")
    seed = json.loads((backend_dir / "seed_data" / "sources.json").read_text(encoding="utf-8"))
    if not seed:
        raise RuntimeError("Public case source list is empty")
    for source in seed:
        original = backend_dir / "seed_data" / "originals" / source["original_name"]
        if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest() != source["original_sha256"]:
            raise RuntimeError("Public source original missing or hash mismatch")
    copy_tree(ROOT / "frontend" / "dist", stage / "frontend" / "dist")
    copy_tree(HERE / "runtime", stage / "runtime", extra_ignores=("tests",))
    (stage / "runtime" / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\n..\n../backend\nimport site\n", encoding="utf-8"
    )
    # assets contains only curated public-case sources, never data/ or config/local.json.
    if (ROOT / "assets").exists():
        copy_tree(ROOT / "assets", stage / "assets")
    (stage / "data").mkdir()
    (stage / "config").mkdir()
    (stage / "config" / "trial.json").write_text(json.dumps(trial, ensure_ascii=False, indent=2), encoding="utf-8")
    (stage / "packaging").mkdir()
    shutil.copy2(HERE / "launcher.py", stage / "packaging" / "launcher.py")
    shutil.copy2(HERE / "runtime_manifest.json", stage / "packaging" / "runtime_manifest.json")
    for name in ("启动知向联网版.cmd", "停止知向联网版.cmd", "启动知向MCP.cmd", "MCP配置示例.json", "使用说明.md", "先读我.txt"):
        shutil.copy2(ROOT / name, stage / name)
    collect_licenses(stage)
    # Confirm that the authorized key is only present in the backend trial config.
    key_bytes = trial["api_key"].encode("utf-8")
    for file in stage.rglob("*"):
        if not file.is_file():
            continue
        relative = file.relative_to(stage).as_posix()
        if key_bytes in file.read_bytes() and relative != "config/trial.json":
            raise RuntimeError("Trial key found outside intended backend config; package build stopped.")
        if file.name in ("local.json", "knowledge.sqlite3", "instance.json", ".env") or file.suffix in (".log", ".db", ".sqlite3"):
            raise RuntimeError("Personal or runtime data would enter package; package build stopped.")
    manifest = {}
    for file in sorted(stage.rglob("*")):
        if file.is_file():
            relative = file.relative_to(stage).as_posix()
            # Avoid publishing a secret-bearing configuration checksum separately.
            if relative != "config/trial.json":
                manifest[relative] = hashlib.sha256(file.read_bytes()).hexdigest()
    (stage / "packaging" / "file_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "知向联网版_Windows体验包.zip"
    temp = build_root / "package.zip"
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(stage.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(build_root))
    shutil.copy2(temp, output)
    result = {"zip": str(output), "stage": str(stage), "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "clean_data": True, "trial_config_included": True, "trial_model": trial["model"], "trial_key_only_in_backend_config": True}
    (HERE / "last_build.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Build failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
