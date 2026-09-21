"""Build-only: vendor the official Windows x64 runtime and Python dependencies."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
VERSION = "3.13.15"
URL = f"https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip"
SHA256 = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"


def main():
    cache = HERE / "downloads"
    cache.mkdir(exist_ok=True)
    archive = cache / f"python-{VERSION}-embed-amd64.zip"
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=120) as response:
            archive.write_bytes(response.read())
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != SHA256:
        raise RuntimeError("Official Python archive SHA-256 mismatch; refusing to unpack.")
    runtime = (HERE / "runtime").resolve()
    if runtime.parent != HERE.resolve():
        raise RuntimeError("Unexpected runtime destination")
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir()
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            destination = (runtime / item.filename).resolve()
            if not destination.is_relative_to(runtime):
                raise RuntimeError("Archive path escapes runtime directory")
        package.extractall(runtime)
    vendor = runtime / "Lib" / "site-packages"
    requirements = HERE / "runtime_requirements.lock"
    if not requirements.exists():
        requirements = HERE.parent / "backend" / "requirements.txt"
    arguments = ["-r", str(requirements)] if requirements.exists() else ["requests>=2.32,<3", "pypdf>=5,<7"]
    subprocess.run([
        sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
        "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.13",
        "--implementation", "cp", "--abi", "cp313", "--target", str(vendor),
        "--no-compile", *arguments,
    ], check=True)
    # Application-local module search; original interpreter binaries are unchanged.
    (runtime / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\n..\n../backend\n../../backend\nimport site\n",
        encoding="utf-8",
    )
    check = subprocess.run([
        str(runtime / "python.exe"), "-c",
        "import sys,ssl,sqlite3,requests,pypdf,importlib.metadata,json; "
        "print(json.dumps({'python':sys.version.split()[0], 'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}}))",
    ], capture_output=True, text=True, check=True)
    metadata = json.loads(check.stdout)
    (HERE / "runtime_requirements.lock").write_text(
        "\n".join(f"{name}=={version}" for name, version in sorted(metadata["packages"].items())) + "\n",
        encoding="utf-8",
    )
    metadata.update({"url": URL, "sha256": SHA256, "platform": "Windows x64", "modifications": "python313._pth application paths and vendored dependencies only"})
    (HERE / "runtime_manifest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=True))


if __name__ == "__main__":
    main()
