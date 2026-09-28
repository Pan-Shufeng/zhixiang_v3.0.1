"""Verify and extract the pinned official Windows x64 Node.js runtime."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
VERSION = "24.19.0"
SHA256 = "57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73"
URL = f"https://nodejs.org/dist/v{VERSION}/node-v{VERSION}-win-x64.zip"


def main():
    cache = HERE / "downloads"
    cache.mkdir(exist_ok=True)
    archive = cache / f"node-v{VERSION}-win-x64.zip"
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Node.js ZIP SHA-256 与官方发布值不符，未继续解压。")
    target = HERE / "node-runtime"
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in ("node.exe", "LICENSE"):
            member = f"node-v{VERSION}-win-x64/{name}"
            (target / name).write_bytes(bundle.read(member))
    print(f"Node.js {VERSION} Windows x64 已核对：{target}")


if __name__ == "__main__":
    main()
