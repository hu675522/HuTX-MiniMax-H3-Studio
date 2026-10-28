from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping

from .fal_models import FalMediaUrls, FalValidationError
from .gh_video_request import NormalizedMediaEntry, NormalizedVideoRequest
from .fal_credentials import FalLogFilter, redact_fal_secrets
from .fal_upload import prepare_fal_upload_path, upload_diagnostic

LOGGER = logging.getLogger(__name__)
LOGGER.addFilter(FalLogFilter())


REFERENCE_FILE_LIMIT = 12
REFERENCE_DURATION_MIN = 2.0
REFERENCE_DURATION_MAX = 15.0
REFERENCE_COMBINED_DURATION_MAX = 15.0
CACHE_VERSION = 1


def _folder_paths():
    return importlib.import_module("folder_paths")


def resolve_input_path(relative_name: str) -> Path:
    """Resolve one normalized media name strictly inside ComfyUI's input tree."""
    name = str(relative_name or "").strip()
    if name.endswith(" [input]"):
        name = name[:-8]
    if not name:
        raise FalValidationError("An active normalized media name is empty.")
    input_root = Path(_folder_paths().get_input_directory()).resolve()
    candidate = (input_root / name).resolve()
    try:
        candidate.relative_to(input_root)
    except ValueError as exc:
        raise FalValidationError(f"Media path escapes the ComfyUI input directory: {relative_name}") from exc
    if not candidate.is_file():
        raise FalValidationError(f"ComfyUI input media file does not exist: {relative_name}")
    return candidate


def probe_duration(path: Path) -> float:
    """Read media duration through PyAV without decoding every frame/sample."""
    try:
        av = importlib.import_module("av")
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyAV is required to inspect fal reference media durations.") from exc
    with av.open(str(path)) as container:
        if container.duration is not None:
            return float(container.duration) / float(av.time_base)
        durations = [
            float(stream.duration * stream.time_base)
            for stream in container.streams
            if stream.duration is not None and stream.time_base is not None
        ]
    if not durations:
        raise FalValidationError(f"Could not determine media duration: {path.name}")
    return max(durations)


def probe_image_size(path: Path) -> tuple[int, int]:
    """Read reference image dimensions without retaining decoded pixel data."""
    try:
        image_module = importlib.import_module("PIL.Image")
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pillow is required to estimate fal reference image cost.") from exc
    with image_module.open(path) as image:
        width, height = image.size
    if width <= 0 or height <= 0:
        raise FalValidationError(f"Could not determine valid image dimensions: {path.name}")
    return int(width), int(height)


@dataclass(frozen=True)
class InspectedMedia:
    item: NormalizedMediaEntry
    path: Path
    source_duration: float | None = None
    effective_duration: float | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class MediaInspection:
    first_frame: InspectedMedia | None
    last_frame: InspectedMedia | None
    reference_images: tuple[InspectedMedia, ...]
    reference_videos: tuple[InspectedMedia, ...]
    reference_audios: tuple[InspectedMedia, ...]


def _inspect_item(
    item: NormalizedMediaEntry | None, *, include_image_size: bool = False
) -> InspectedMedia | None:
    if not item:
        return None
    path = resolve_input_path(item.name)
    if include_image_size:
        width, height = probe_image_size(path)
        return InspectedMedia(item=item, path=path, width=width, height=height)
    return InspectedMedia(item=item, path=path)


def _validate_duration(label: str, duration: float) -> None:
    if not REFERENCE_DURATION_MIN <= duration <= REFERENCE_DURATION_MAX:
        raise FalValidationError(
            f"{label} duration must be {REFERENCE_DURATION_MIN:g}-{REFERENCE_DURATION_MAX:g}s; "
            f"got {duration:.3f}s."
        )


def inspect_manifest_media(request: NormalizedVideoRequest) -> MediaInspection:
    """Resolve normalized request files and enforce fal Reference limits."""
    if not isinstance(request, NormalizedVideoRequest):
        raise TypeError("inspect_manifest_media requires NormalizedVideoRequest")
    image_items = request.reference_images
    video_items = request.reference_videos
    audio_items = request.reference_audios
    reference_total = len(image_items) + len(video_items) + len(audio_items)
    if reference_total > REFERENCE_FILE_LIMIT:
        raise FalValidationError(
            f"MiniMax H3 Max Reference supports at most {REFERENCE_FILE_LIMIT} total files; "
            f"got {reference_total}."
        )
    if audio_items and not image_items and not video_items:
        raise FalValidationError(
            "MiniMax H3 Max Reference does not allow audio as the only reference input."
        )

    first = _inspect_item(request.first_frame)
    last = _inspect_item(request.last_frame)
    images = tuple(_inspect_item(item, include_image_size=True) for item in image_items)

    videos: list[InspectedMedia] = []
    for item in video_items:
        path = resolve_input_path(item.name)
        duration = probe_duration(path)
        _validate_duration(item.slot, duration)
        videos.append(InspectedMedia(item=item, path=path, source_duration=duration, effective_duration=duration))
    combined_video_duration = sum(float(item.effective_duration or 0) for item in videos)
    if combined_video_duration > REFERENCE_COMBINED_DURATION_MAX:
        raise FalValidationError(
            "MiniMax H3 Max reference videos may total at most "
            f"{REFERENCE_COMBINED_DURATION_MAX:g}s; got {combined_video_duration:.3f}s."
        )

    audios: list[InspectedMedia] = []
    for item in audio_items:
        path = resolve_input_path(item.name)
        source_duration = probe_duration(path)
        trim_start = float(item.trim_start or 0)
        raw_end = item.trim_end
        trim_end = float(raw_end) if raw_end is not None else None
        if trim_start < 0:
            raise FalValidationError(f"{item.slot} trim_start cannot be negative.")
        if trim_start >= source_duration:
            raise FalValidationError(f"{item.slot} trim_start is outside the source audio.")
        if trim_end is not None:
            if trim_end <= trim_start:
                raise FalValidationError(f"{item.slot} trim_end must be greater than trim_start.")
            if trim_end > source_duration + 0.01:
                raise FalValidationError(
                    f"{item.slot} trim_end {trim_end:.3f}s exceeds source duration {source_duration:.3f}s."
                )
        effective_duration = (trim_end if trim_end is not None else source_duration) - trim_start
        _validate_duration(item.slot, effective_duration)
        audios.append(
            InspectedMedia(
                item=item,
                path=path,
                source_duration=source_duration,
                effective_duration=effective_duration,
            )
        )
    combined_audio_duration = sum(float(item.effective_duration or 0) for item in audios)
    if combined_audio_duration > REFERENCE_COMBINED_DURATION_MAX:
        raise FalValidationError(
            "MiniMax H3 Max reference audios may total at most "
            f"{REFERENCE_COMBINED_DURATION_MAX:g}s; got {combined_audio_duration:.3f}s."
        )

    return MediaInspection(
        first_frame=first,
        last_frame=last,
        reference_images=tuple(item for item in images if item is not None),
        reference_videos=tuple(videos),
        reference_audios=tuple(audios),
    )


def _default_cache_directory() -> Path:
    try:
        root = Path(_folder_paths().get_temp_directory())
    except (AttributeError, ModuleNotFoundError):
        root = Path(tempfile.gettempdir())
    return root / "goohai_minimax_h3_fal"


def _ffmpeg_executable() -> str:
    try:
        imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError("FFmpeg is required to preprocess fal reference media.") from exc


def _run_ffmpeg(arguments: list[str]) -> None:
    completed = subprocess.run(
        [_ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "unknown FFmpeg error").strip()
        raise RuntimeError(f"fal media preprocessing failed: {detail}")


def preprocess_media(source: Path, destination: Path, transform: Mapping[str, Any]) -> Path:
    operation = transform.get("operation")
    if not operation:
        return source
    destination.parent.mkdir(parents=True, exist_ok=True)
    if operation == "remove_audio":
        _run_ffmpeg([
            "-i", str(source), "-map", "0:v:0", "-c:v", "copy", "-an", str(destination)
        ])
    elif operation == "trim_audio":
        start = float(transform["trim_start"])
        end = transform.get("trim_end")
        arguments = ["-ss", f"{start:.9f}", "-i", str(source)]
        if end is not None:
            arguments.extend(["-t", f"{float(end) - start:.9f}"])
        arguments.extend(["-vn", "-c:a", "pcm_s16le", str(destination)])
        _run_ffmpeg(arguments)
    else:
        raise FalValidationError(f"Unknown fal media transform: {operation}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"fal media preprocessing did not create {destination.name}")
    return destination


class FalUploadCache:
    """Persistent upload URL cache keyed by source identity and transformations."""

    def __init__(self, cache_directory: str | os.PathLike[str] | None = None):
        self.directory = Path(cache_directory) if cache_directory else _default_cache_directory()
        self.processed_directory = self.directory / "processed"
        self.index_path = self.directory / "upload_cache_v1.json"
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            entries = data.get("entries", {}) if data.get("version") == CACHE_VERSION else {}
            self._entries = entries if isinstance(entries, dict) else {}
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            self._entries = {}
        return self._entries

    @staticmethod
    def _key_data(source: Path, transform: Mapping[str, Any]) -> dict[str, Any]:
        stat = source.stat()
        return {
            "absolute_path": str(source.resolve()),
            "file_size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "transform": dict(transform),
        }

    @staticmethod
    def _key(key_data: Mapping[str, Any]) -> str:
        encoded = json.dumps(dict(key_data), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": CACHE_VERSION, "entries": self._entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.index_path)

    def upload(
        self,
        source: Path,
        *,
        transform: Mapping[str, Any] | None,
        uploader: Callable[[str], str],
        timing: MutableMapping[str, float] | None = None,
        media_kind: str = "media",
        slot: str = "",
    ) -> str:
        if timing is not None:
            timing.setdefault("upload_seconds", 0.0)
        transform = dict(transform or {})
        key_data = self._key_data(source, transform)
        key = self._key(key_data)
        with self._lock:
            cached = self._load().get(key)
            if isinstance(cached, dict) and isinstance(cached.get("url"), str) and cached["url"]:
                return cached["url"]

            upload_path = source
            if transform:
                suffix = source.suffix if transform.get("operation") == "remove_audio" else ".wav"
                upload_path = self.processed_directory / f"{key}{suffix}"
                if not upload_path.is_file() or upload_path.stat().st_size == 0:
                    started = time.perf_counter()
                    try:
                        upload_path = preprocess_media(source, upload_path, transform)
                    finally:
                        if timing is not None:
                            timing["media_prepare_seconds"] = timing.get(
                                "media_prepare_seconds", 0.0
                            ) + (time.perf_counter() - started)
            started = time.perf_counter()
            try:
                with prepare_fal_upload_path(upload_path) as prepared:
                    diagnostic = redact_fal_secrets(json.dumps(upload_diagnostic(
                        source, prepared, kind=media_kind, slot=slot,
                    ), ensure_ascii=True))
                    LOGGER.info("Fal upload item: %s", diagnostic)
                    try:
                        url = str(uploader(str(prepared)))
                    except Exception:
                        LOGGER.warning("Fal upload item failed: %s", diagnostic)
                        raise
            finally:
                if timing is not None:
                    timing["upload_seconds"] = timing.get("upload_seconds", 0.0) + (
                        time.perf_counter() - started
                    )
            if not url:
                raise RuntimeError("fal storage upload returned an empty URL")
            self._load()[key] = {
                "url": url,
                "source": key_data,
                "created_at": int(time.time()),
            }
            self._save()
            return url


def upload_manifest_media(
    inspection: MediaInspection,
    *,
    uploader: Callable[[str], str],
    cache: FalUploadCache | None = None,
    timing: MutableMapping[str, float] | None = None,
) -> FalMediaUrls:
    cache = cache or FalUploadCache()

    def upload(item: InspectedMedia | None, transform: Mapping[str, Any] | None = None) -> str | None:
        if item is None:
            return None
        return cache.upload(
            item.path,
            transform=transform,
            uploader=uploader,
            timing=timing,
            slot=item.item.slot,
            media_kind=(
                item.item.slot if item.item.slot in {"first_frame", "last_frame", "hybrid_audio"}
                else "reference_image" if item in inspection.reference_images
                else "reference_video" if item in inspection.reference_videos
                else "reference_audio"
            ),
        )

    images = tuple(upload(item) for item in inspection.reference_images)
    videos = []
    for item in inspection.reference_videos:
        transform = (
            {"operation": "remove_audio", "version": 1}
            if item.item.muted
            else None
        )
        videos.append(upload(item, transform))
    audios = []
    for item in inspection.reference_audios:
        start = float(item.item.trim_start or 0)
        end = item.item.trim_end
        transform = None
        if start != 0 or end is not None:
            transform = {
                "operation": "trim_audio",
                "trim_start": start,
                "trim_end": float(end) if end is not None else None,
                "codec": "pcm_s16le",
                "version": 1,
            }
        audios.append(upload(item, transform))
    return FalMediaUrls(
        first_frame=upload(inspection.first_frame),
        last_frame=upload(inspection.last_frame),
        reference_images=tuple(str(url) for url in images if url is not None),
        reference_videos=tuple(str(url) for url in videos if url is not None),
        reference_audios=tuple(str(url) for url in audios if url is not None),
    )
