"""Build the full source distribution, including tests, docs and assets.

Excludes the local voice runtime, caches, build output and Git metadata.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "plugin_meta.py").read_text(encoding="utf-8").split('PLUGIN_VERSION = "', 1)[1].split('"', 1)[0]
OUTPUT = ROOT / "dist" / f"HuTX-MiniMax-H3-Studio-v{VERSION}-full.zip"
PREFIX = "HuTX-MiniMax-H3-Studio"
EXCLUDE_DIRS = {
    ".git", ".speech-runtime", ".test-artifacts", ".test-deps", ".pytest_cache",
    ".venv", "dist", "node_modules", "__pycache__", "video",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp"}


def collect() -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        base = Path(dirpath)
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink() or path.suffix.lower() in EXCLUDE_SUFFIXES:
                continue
            files.append(path)
    return files


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    files = collect()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": PREFIX,
        "version": VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "files": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in files},
    }
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, f"{PREFIX}/{path.relative_to(ROOT).as_posix()}")
        archive.writestr(f"{PREFIX}/DISTRIBUTION.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"{OUTPUT}: {len(files)} files, {OUTPUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
