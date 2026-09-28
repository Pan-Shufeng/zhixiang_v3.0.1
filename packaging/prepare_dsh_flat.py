"""Install pinned DSH dependencies in a ZIP-safe, junction-free layout."""
from pathlib import Path
import os
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    target = HERE / "dsh-flat"
    target.mkdir(exist_ok=True)
    for name in ("package.json", "pnpm-lock.yaml"):
        shutil.copy2(ROOT / "dsh" / name, target / name)
    config = (ROOT / "dsh" / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    (target / "pnpm-workspace.yaml").write_text("nodeLinker: hoisted\n" + config, encoding="utf-8")
    pnpm = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if not pnpm:
        raise RuntimeError("构建机需要 pnpm 11；普通体验者不需要安装。")
    subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=target, check=True)
    modules = target / "node_modules"
    if not (modules / "@deepseek-ai" / "dsh" / "lib" / "bin.js").is_file():
        raise RuntimeError("DSH CLI 未正确安装。")
    if any(path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()) for path in modules.rglob("*")):
        raise RuntimeError("依赖目录还有链接，不能做便携 ZIP。请在新的干净目录安装。")
    print(f"固定版本 DSH 已安装到无链接目录：{modules}")


if __name__ == "__main__":
    main()
