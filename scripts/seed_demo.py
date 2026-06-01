"""One-shot helper: write a demo profile.yaml into data/profile/ if missing."""

from __future__ import annotations

import shutil
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "data" / "profile" / "profile.yaml.example"
    dst = repo_root / "data" / "profile" / "profile.yaml"
    if dst.exists():
        print(f"[skip] {dst} already exists")
        return
    shutil.copy(src, dst)
    print(f"[ok] wrote {dst}")


if __name__ == "__main__":
    main()
