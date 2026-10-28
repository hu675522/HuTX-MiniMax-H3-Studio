"""Install or package the isolated CosyVoice runtime; never change ComfyUI Python.

This file intentionally uses only the standard library of the launcher Python.
It is an operator tool, not imported by the ComfyUI extension.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".speech-runtime"
LOCK = json.loads((ROOT / "speech_runtime_lock.json").read_text(encoding="utf-8"))
MODEL_NAME = "Fun-CosyVoice3-0.5B-2512"
UV_VERSION = "0.12.13"
TORCH_WHEEL = "torch-2.3.1+cu121-cp310-cp310-win_amd64.whl"
TORCH_SHA256 = "bf1438aeb124fc36ae2d6b4b5c76d751d47a9fc3d7b15291b41f0caa8d5bf27b"
TORCH_URL = "https://download.pytorch.org/whl/cu121/torch-2.3.1%2Bcu121-cp310-cp310-win_amd64.whl"
TORCHAUDIO_URL = "https://download.pytorch.org/whl/cu121/torchaudio-2.3.1%2Bcu121-cp310-cp310-win_amd64.whl"
UV_URL = f"https://releases.astral.sh/github/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
REQUIRED = (
    "env/Scripts/python.exe",
    "CosyVoice/cosyvoice/cli/cosyvoice.py",
    f"models/{MODEL_NAME}/hutx-model-lock.json",
    f"models/{MODEL_NAME}/llm.pt",
    f"models/{MODEL_NAME}/flow.pt",
    f"models/{MODEL_NAME}/hift.pt",
    f"models/{MODEL_NAME}/speech_tokenizer_v3.onnx",
    "models/quality/base.pt",
    "models/quality/silero_vad.onnx",
    "models/wetext/en/tn/tagger.fst",
    "models/wetext/en/tn/verbalizer.fst",
    "models/wetext/zh/tn/tagger.fst",
    "models/wetext/zh/tn/verbalizer.fst",
)
PACK_DIRS = ("CosyVoice", "env", "models", "python")
PACK_FILES = ("environment-ready.json", "environment-freeze.txt")


def log(message: str) -> None:
    print(message, flush=True)


def run(*args: str, env: dict[str, str] | None = None) -> None:
    log("运行：" + " ".join(str(a) for a in args[:2]) + (" …" if len(args) > 2 else ""))
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, path: Path, expected_hash: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and (not expected_hash or sha256(path) == expected_hash):
        log(f"已校验：{path.name}")
        return
    partial = path.with_name(path.name + ".download")
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "HuTX-Speech-Runtime-Installer/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=180) as response:
        append = offset and response.status == 206
        if append and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
            raise RuntimeError(f"服务器返回了错误的续传范围：{url}")
        with partial.open("ab" if append else "wb") as output:
            while block := response.read(4 * 1024 * 1024):
                output.write(block)
    if expected_hash and sha256(partial) != expected_hash:
        raise RuntimeError(f"下载校验失败：{path.name}。请删除 {partial.name} 后重试。")
    partial.replace(path)
    log(f"下载完成：{path.name}")


def unpack_zip(archive: Path, destination: Path, *, strip_top: bool = False) -> None:
    """Extract ZIP entries only below destination; reject links and odd paths."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            raw = PurePosixPath(info.filename)
            parts = raw.parts[1:] if strip_top else raw.parts
            if raw.is_absolute() or any(part in (".", "..") for part in raw.parts):
                raise RuntimeError(f"运行包含非法路径：{info.filename}")
            if not parts:
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError("运行包不允许符号链接。")
            target = destination.joinpath(*parts)
            if not target.resolve().is_relative_to(destination):
                raise RuntimeError(f"运行包含越界路径：{info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as inp, target.open("wb") as out:
                    shutil.copyfileobj(inp, out, 4 * 1024 * 1024)


def check_files(runtime: Path) -> None:
    missing = [name for name in REQUIRED if not (runtime / name).is_file()]
    if missing:
        raise RuntimeError("运行环境缺少文件：" + ", ".join(missing[:6]))
    model_lock = json.loads((runtime / f"models/{MODEL_NAME}/hutx-model-lock.json").read_text(encoding="utf-8"))
    for key in ("commit", "matcha_commit", "model_revision", "torch", "torchaudio"):
        if model_lock.get(key) != LOCK[key]:
            raise RuntimeError(f"运行包版本不匹配：{key}")


def python_home(runtime: Path) -> Path:
    candidates = sorted((runtime / "python").glob("cpython-3.10.21-windows-x86_64-none"))
    if len(candidates) != 1 or not (candidates[0] / "python.exe").is_file():
        raise RuntimeError("运行包缺少固定版本的 Python 3.10.21。")
    return candidates[0]


def repair_venv(runtime: Path) -> None:
    config = runtime / "env/pyvenv.cfg"
    if not config.is_file():
        raise RuntimeError("运行包缺少 env/pyvenv.cfg。")
    home = str(python_home(runtime))
    lines = config.read_text(encoding="utf-8").splitlines()
    lines = ["home = " + home if line.startswith("home = ") else line for line in lines]
    if not any(line.startswith("home = ") for line in lines):
        lines.insert(0, "home = " + home)
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("已修复独立 Python 环境路径。")


def check(runtime: Path, *, smoke: bool = True) -> None:
    check_files(runtime)
    home = python_home(runtime)
    cfg = (runtime / "env/pyvenv.cfg").read_text(encoding="utf-8")
    if f"home = {home}" not in cfg.splitlines():
        raise RuntimeError("Python 环境仍指向原电脑；请运行安装器修复。")
    if smoke:
        run(str(runtime / "env/Scripts/python.exe"), "-c",
            "import sys, torch, torchaudio, onnxruntime, soundfile; "
            "assert sys.version_info[:2] == (3, 10); "
            "assert torch.__version__.startswith('2.3.1+cu121'); "
            "assert torchaudio.__version__.startswith('2.3.1+cu121'); "
            "print('CosyVoice Python dependencies OK')")
    log("本地 CosyVoice 运行环境检查通过。")


def package(output: Path) -> None:
    check_files(RUNTIME)
    python_home(RUNTIME)
    output = output.resolve()
    if output == RUNTIME or output.is_relative_to(RUNTIME):
        raise RuntimeError("运行包不能写入运行目录内。")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    if temporary.exists():
        raise RuntimeError(f"请先处理上次未完成的包：{temporary}")
    log("开始制作独立运行包；不包含 uv-cache、Torch 安装包、测试文件或个人凭证。")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as target:
            for dirname in PACK_DIRS:
                base = RUNTIME / dirname
                if not base.is_dir():
                    raise RuntimeError(f"运行目录缺少 {dirname}")
                for root, dirs, files in os.walk(base, followlinks=False):
                    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".temp")
                              and not (Path(root) / d).is_symlink()]
                    for name in files:
                        file = Path(root) / name
                        if file.is_symlink() or name == ".git" or file.suffix == ".pyc":
                            continue
                        target.write(file, file.relative_to(RUNTIME).as_posix())
            for name in PACK_FILES:
                file = RUNTIME / name
                if file.is_file():
                    target.write(file, name)
            target.writestr("hutx-package.json", json.dumps({
                "format": 1, "plugin": "HuTX-MiniMax-H3-Studio",
                "model_revision": LOCK["model_revision"], "torch": LOCK["torch"]}))
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    checksum = sha256(output)
    output.with_name(output.name + ".sha256").write_text(
        f"{checksum}  {output.name}\n", encoding="ascii")
    log(f"运行包已生成：{output} ({output.stat().st_size / 1024**3:.2f} GiB)")


def install_bundle(bundle: Path) -> None:
    if RUNTIME.exists():
        raise RuntimeError("当前目录已有 .speech-runtime。请先检查现有环境，避免覆盖用户模型。")
    bundle = bundle.resolve()
    if not bundle.is_file():
        raise RuntimeError(f"找不到运行包：{bundle}")
    checksum_file = bundle.with_name(bundle.name + ".sha256")
    if checksum_file.is_file():
        expected = checksum_file.read_text(encoding="ascii").split()[0].lower()
        if len(expected) != 64 or sha256(bundle) != expected:
            raise RuntimeError("运行包 SHA-256 校验失败；请重新复制 ZIP 文件。")
    with zipfile.ZipFile(bundle) as source:
        required_bytes = sum(item.file_size for item in source.infolist())
    if shutil.disk_usage(ROOT).free < required_bytes + 1024**3:
        raise RuntimeError("目标磁盘可用空间不足，无法解压语音运行包。")
    stage = ROOT / ".speech-runtime.installing"
    if stage.exists():
        raise RuntimeError("发现未完成的 .speech-runtime.installing；请检查后手动移走再重试。")
    log(f"正在解压运行包：{bundle}")
    unpack_zip(bundle, stage)
    manifest = stage / "hutx-package.json"
    if not manifest.is_file():
        raise RuntimeError("不是 HuTX 语音运行包。")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if (metadata.get("format"), metadata.get("model_revision"), metadata.get("torch")) != (
        1, LOCK["model_revision"], LOCK["torch"]):
        raise RuntimeError("运行包版本不匹配。")
    check_files(stage)
    python_home(stage)
    stage.rename(RUNTIME)
    repair_venv(RUNTIME)
    check(RUNTIME)
    (RUNTIME / "environment-ready.json").write_text(json.dumps({
        "python": "3.10.21", "torch": LOCK["torch"], "offline_worker_smoke": False}), encoding="utf-8")


def download_code(runtime: Path, repository: str, commit: str,
                  destination: Path, required_file: Path) -> None:
    stamp = destination / ".hutx-revision"
    if required_file.is_file() and stamp.is_file() and stamp.read_text(encoding="ascii").strip() == commit:
        return
    archive = runtime / "downloads" / (repository.split("/")[-1] + ".zip")
    download(f"https://github.com/{repository}/archive/{commit}.zip", archive)
    unpack_zip(archive, destination, strip_top=True)
    if not required_file.is_file():
        raise RuntimeError(f"下载的源码缺少文件：{required_file.name}")
    stamp.write_text(commit + "\n", encoding="ascii")


def online(keep_cache: bool) -> None:
    if sys.platform != "win32" or os.environ.get("PROCESSOR_ARCHITECTURE", "").lower() not in ("amd64", ""):
        raise RuntimeError("当前安装器仅支持 Windows x64。")
    if RUNTIME.is_symlink():
        raise RuntimeError("现有运行目录是链接；请在真实目录上安装。")
    if not RUNTIME.exists() and shutil.disk_usage(ROOT).free < 20 * 1024**3:
        raise RuntimeError("在线安装需要目标磁盘至少 20 GiB 可用空间。")
    RUNTIME.mkdir(exist_ok=True)
    uv = RUNTIME / "tools/uv.exe"
    if not uv.is_file():
        archive = RUNTIME / "downloads/uv.zip"
        download(UV_URL, archive)
        unpack_zip(archive, RUNTIME / "tools")
        if not uv.is_file():
            raise RuntimeError("uv 官方压缩包中未找到 uv.exe。")
    environment = os.environ.copy()
    environment["UV_PYTHON_INSTALL_DIR"] = str(RUNTIME / "python")
    environment["UV_CACHE_DIR"] = str(RUNTIME / "uv-cache")
    environment["UV_PYTHON_PREFERENCE"] = "only-managed"
    run(str(uv), "python", "install", "3.10.21", env=environment)
    env_python = RUNTIME / "env/Scripts/python.exe"
    if not env_python.is_file():
        run(str(uv), "venv", "--python", "3.10.21", str(RUNTIME / "env"), env=environment)
    repair_venv(RUNTIME)
    wheel = RUNTIME / "wheels" / TORCH_WHEEL
    download(TORCH_URL, wheel, TORCH_SHA256)
    run(str(uv), "pip", "install", "--python", str(env_python), str(wheel),
        TORCHAUDIO_URL, env=environment)
    run(str(uv), "pip", "install", "--python", str(env_python), "-r",
        str(ROOT / "speech_requirements.txt"), "--build-constraint",
        str(ROOT / "speech_build_constraints.txt"), env=environment)
    download_code(RUNTIME, "FunAudioLLM/CosyVoice", LOCK["commit"], RUNTIME / "CosyVoice",
                  RUNTIME / "CosyVoice/cosyvoice/cli/cosyvoice.py")
    download_code(RUNTIME, "shivammehta25/Matcha-TTS", LOCK["matcha_commit"],
                  RUNTIME / "CosyVoice/third_party/Matcha-TTS",
                  RUNTIME / "CosyVoice/third_party/Matcha-TTS/matcha/models/matcha_tts.py")
    for script in ("download_speech_runtime.py", "download_speech_quality.py", "download_wetext_runtime.py"):
        path = ROOT / "tools" / script
        if not path.is_file():
            raise RuntimeError(f"插件安装包缺少下载组件：{path}")
        run(str(env_python), str(path))
    run(str(env_python), "-c", "import torch, torchaudio; "
        "assert torch.__version__.startswith('2.3.1+cu121'); "
        "assert torchaudio.__version__.startswith('2.3.1+cu121')")
    (RUNTIME / "environment-ready.json").write_text(json.dumps({
        "python": "3.10.21", "torch": LOCK["torch"], "offline_worker_smoke": False}), encoding="utf-8")
    check(RUNTIME)
    if not keep_cache:
        for relative in ("uv-cache", "downloads", "wheels"):
            target = RUNTIME / relative
            if (target.is_dir() and not target.is_symlink()
                    and target.resolve().is_relative_to(RUNTIME.resolve())):
                shutil.rmtree(target)
        log("已清理下载缓存和安装包。")


def main() -> None:
    parser = argparse.ArgumentParser(description="HuTX 本地 CosyVoice 一键安装/迁移")
    parser.add_argument("--mode", choices=("auto", "check", "online", "bundle", "pack"), default="auto")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keep-cache", action="store_true")
    args = parser.parse_args()
    mode = args.mode
    if mode == "auto":
        if RUNTIME.is_dir():
            try:
                check_files(RUNTIME)
                mode = "check"
            except (OSError, ValueError, RuntimeError):
                mode = "online"
        elif args.bundle or (ROOT / "HuTX-CosyVoice-Runtime.zip").is_file():
            mode = "bundle"
        else:
            mode = "online"
    if mode == "check":
        if RUNTIME.is_dir():
            repair_venv(RUNTIME)
            check(RUNTIME)
        else:
            raise RuntimeError("没有找到 .speech-runtime；请选择在线安装或提供运行包。")
    elif mode == "pack":
        package(args.output or ROOT / ".test-artifacts/runtime-packages/HuTX-CosyVoice-Runtime.zip")
    elif mode == "bundle":
        install_bundle(args.bundle or ROOT / "HuTX-CosyVoice-Runtime.zip")
    else:
        online(args.keep_cache)
    log("完成。请重启 ComfyUI 后使用本地 CosyVoice。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f"安装失败：{exc}", file=sys.stderr, flush=True)
        sys.exit(1)
