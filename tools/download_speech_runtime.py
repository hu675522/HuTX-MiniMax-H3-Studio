"""Download the pinned CosyVoice model, preferring verified ModelScope files."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "speech_runtime_lock.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((ROOT / "tools/speech_model_manifest.json").read_text(encoding="utf-8"))
if MANIFEST["model"] != LOCK["model"] or MANIFEST["model_revision"] != LOCK["model_revision"]:
    raise RuntimeError("Pinned model manifest does not match the runtime lock")
MODEL_ROOT = ROOT / ".speech-runtime/models/Fun-CosyVoice3-0.5B-2512"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def modelscope_files() -> dict[str, dict]:
    url = f'https://modelscope.cn/api/v1/models/{LOCK["model"]}/repo/files?Revision=master&Recursive=true'
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            data = json.load(response)
        return {item["Path"]: item for item in data["Data"]["Files"] if item["Type"] == "blob"}
    except (OSError, ValueError, KeyError, TypeError):
        print("ModelScope directory unavailable; using pinned Hugging Face revision.", flush=True)
        return {}


def download_one(entry: dict, alternate: dict | None) -> str:
    name, size, expected = entry["path"], entry["size"], entry["sha256"]
    target = MODEL_ROOT / name
    if not target.resolve().is_relative_to(MODEL_ROOT.resolve()):
        raise RuntimeError("Invalid model manifest path")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == size and digest(target) == expected:
        return name + " verified existing"
    if alternate and alternate.get("Size") == size and alternate.get("Sha256", "").lower() == expected:
        url = (f'https://modelscope.cn/api/v1/models/{LOCK["model"]}/repo?Revision='
               + urllib.parse.quote(str(alternate["Revision"]), safe="")
               + '&FilePath=' + urllib.parse.quote(name, safe=""))
    else:
        url = f'https://huggingface.co/{LOCK["model"]}/resolve/{LOCK["model_revision"]}/{name}'
    temporary = target.with_name(target.name + ".download")
    offset = temporary.stat().st_size if temporary.exists() else 0
    while offset < size:
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{size-1}"})
        with urllib.request.urlopen(request, timeout=180) as response:
            if response.status == 206:
                if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise RuntimeError("Invalid model download range: " + name)
                mode = "ab"
            elif response.status == 200:
                offset, mode = 0, "wb"
            else:
                raise RuntimeError("Unexpected model response: " + name)
            previous = offset
            with temporary.open(mode) as output:
                while block := response.read(4 * 1024 * 1024):
                    output.write(block)
                    offset += len(block)
        if offset <= previous:
            raise RuntimeError("Model download made no progress: " + name)
        if offset > size:
            raise RuntimeError("Model download exceeded expected size: " + name)
    if temporary.stat().st_size != size or digest(temporary) != expected:
        raise RuntimeError("Model integrity check failed: " + name)
    temporary.replace(target)
    return name + " verified"


def main() -> None:
    alternatives = modelscope_files()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(download_one, entry, alternatives.get(entry["path"]))
                   for entry in MANIFEST["files"]]
        for future in concurrent.futures.as_completed(futures):
            print(future.result(), flush=True)
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    (MODEL_ROOT / "hutx-model-lock.json").write_text(
        json.dumps(LOCK, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
