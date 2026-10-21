"""Copy the app source into the add-on folder, because a Docker build only sees that folder.

    python scripts/sync_addon.py          # update voice_assist_improver/app
    python scripts/sync_addon.py --check  # exit 1 if it is out of date (used by CI)
"""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "voice_assist_improver" / "app"
FILES = ["pyproject.toml", "README.md", "LICENSE"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")


def build(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in FILES:
        shutil.copy2(ROOT / name, dest / name)
    shutil.copytree(ROOT / "src", dest / "src", ignore=IGNORE)


def same(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__"])
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
    return not mismatch and not errors and all(same(a / d, b / d) for d in cmp.common_dirs)


def main() -> int:
    if "--check" in sys.argv:
        tmp = ROOT / ".addon-check"
        build(tmp)
        try:
            ok = DEST.exists() and same(tmp, DEST)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if not ok:
            print("voice_assist_improver/app is out of date: run python scripts/sync_addon.py")
        return 0 if ok else 1
    build(DEST)
    print(f"synced {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
