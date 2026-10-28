"""Create a small code-only distribution alongside the separate speech runtime."""

import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "HuTX-MiniMax-H3-Studio-v0.3.2.2-code.zip"
DIRS = ("assets", "docs", "locales", "prompt_optimizer", "speech_providers", "tools", "web")
SUFFIXES = {".py", ".md", ".txt", ".json", ".ps1", ".cmd"}


def accepted(path: Path) -> bool:
    return (path.is_file() and not path.is_symlink()
            and not any(part in ("__pycache__", ".git", ".test-artifacts", ".speech-runtime")
                        for part in path.relative_to(ROOT).parts)
            and path.suffix != ".pyc")


def main() -> None:
    files = [path for path in ROOT.iterdir()
             if accepted(path) and (path.suffix in SUFFIXES or path.name in ("LICENSE", ".gitignore"))]
    for name in DIRS:
        files.extend(path for path in (ROOT / name).rglob("*") if accepted(path))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            archive.write(path, "HuTX-MiniMax-H3-Studio/" + path.relative_to(ROOT).as_posix())
    print(f"{OUTPUT}: {len(files)} files, {OUTPUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
