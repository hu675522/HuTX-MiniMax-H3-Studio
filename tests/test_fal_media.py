from __future__ import annotations

import json
import os
import shutil
import sys
import time
import types

import pytest

from hutx_minimax_h3_testpkg import fal_media
from hutx_minimax_h3_testpkg.fal_media import (
    FalUploadCache,
    InspectedMedia,
    MediaInspection,
    inspect_manifest_media,
    resolve_input_path,
    upload_manifest_media,
)
from hutx_minimax_h3_testpkg.fal_models import FalValidationError
from hutx_minimax_h3_testpkg.gh_video_request import (
    NormalizedMediaEntry,
    build_cloud_video_request,
    normalize_video_request,
)


@pytest.fixture
def input_directory(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    input_root.mkdir()
    fake = types.SimpleNamespace(
        get_input_directory=lambda: str(input_root),
        get_temp_directory=lambda: str(tmp_path / "temp"),
    )
    monkeypatch.setitem(sys.modules, "folder_paths", fake)
    return input_root


def base_manifest(**updates):
    value = {
        "schema_version": 1,
        "input_prompt": "test",
        "conditioned_prompt": "test",
        "main_mode": "all_reference",
        "resolved_task": "ref2va",
        "aspect": "adaptive",
        "target": {
            "width": 1024,
            "height": 1024,
            "requested_duration_seconds": 5.0,
            "local_frame_count": 124,
            "local_duration_seconds": 124 / 24,
        },
        "first_frame": None,
        "last_frame": None,
        "reference_images": [],
        "reference_videos": [],
        "reference_audios": [],
        "hybrid_audio": None,
    }
    value.update(updates)
    return normalize_video_request({"source_manifest": value})


def test_resolve_input_path_uses_comfy_input_and_rejects_escape(input_directory):
    media = input_directory / "folder" / "image.png"
    media.parent.mkdir()
    media.write_bytes(b"image")
    assert resolve_input_path("folder/image.png") == media.resolve()
    with pytest.raises(FalValidationError, match="escapes"):
        resolve_input_path("../outside.png")


def test_reference_duration_and_trim_validation(input_directory, monkeypatch):
    for name in ("image.png", "one.mp4", "two.mp4", "audio.wav"):
        (input_directory / name).write_bytes(name.encode())
    durations = {"one.mp4": 5.0, "two.mp4": 6.0, "audio.wav": 12.0}
    monkeypatch.setattr(fal_media, "probe_duration", lambda path: durations[path.name])
    monkeypatch.setattr(fal_media, "probe_image_size", lambda path: (1024, 1024))
    result = inspect_manifest_media(
        base_manifest(
            reference_images=[{"slot": "ref_image_1", "name": "image.png"}],
            reference_videos=[
                {"slot": "ref_video_1", "name": "one.mp4", "muted": False},
                {"slot": "ref_video_3", "name": "two.mp4", "muted": True},
            ],
            reference_audios=[
                {
                    "slot": "ref_audio_2",
                    "name": "audio.wav",
                    "trim_start": 2.0,
                    "trim_end": 7.0,
                }
            ],
        )
    )
    assert result.reference_audios[0].effective_duration == 5.0
    assert sum(item.effective_duration for item in result.reference_videos) == 11.0
    assert (result.reference_images[0].width, result.reference_images[0].height) == (1024, 1024)


def test_reference_combined_duration_is_not_silently_clipped(input_directory, monkeypatch):
    for name in ("image.png", "one.mp4", "two.mp4"):
        (input_directory / name).write_bytes(b"x")
    monkeypatch.setattr(fal_media, "probe_duration", lambda path: 8.0)
    monkeypatch.setattr(fal_media, "probe_image_size", lambda path: (1024, 1024))
    with pytest.raises(FalValidationError, match="total at most 15"):
        inspect_manifest_media(
            base_manifest(
                reference_images=[{"slot": "ref_image_1", "name": "image.png"}],
                reference_videos=[
                    {"slot": "ref_video_1", "name": "one.mp4", "muted": False},
                    {"slot": "ref_video_2", "name": "two.mp4", "muted": False},
                ],
            )
        )


def test_audio_only_is_rejected_before_upload():
    with pytest.raises(FalValidationError, match="only reference"):
        inspect_manifest_media(
            base_manifest(
                reference_audios=[
                    {"slot": "ref_audio_1", "name": "audio.wav", "trim_start": 0, "trim_end": None}
                ]
            )
        )


def test_muted_video_and_trimmed_audio_transform_and_cache(tmp_path, monkeypatch):
    video_path = tmp_path / "video.mp4"
    audio_path = tmp_path / "audio.wav"
    video_path.write_bytes(b"video")
    audio_path.write_bytes(b"audio")
    calls = []

    def fake_preprocess(source, destination, transform):
        calls.append(dict(transform))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination

    monkeypatch.setattr(fal_media, "preprocess_media", fake_preprocess)
    uploads = []

    def uploader(path):
        uploads.append(path)
        return f"https://storage.example/{os.path.basename(path)}"

    inspection = MediaInspection(
        first_frame=None,
        last_frame=None,
        reference_images=(),
        reference_videos=(
            InspectedMedia(
                item=NormalizedMediaEntry(
                    slot="ref_video_1", name="video.mp4", muted=True
                ),
                path=video_path,
                source_duration=5,
                effective_duration=5,
            ),
        ),
        reference_audios=(
            InspectedMedia(
                item=NormalizedMediaEntry(
                    slot="ref_audio_1",
                    name="audio.wav",
                    trim_start=1.0,
                    trim_end=4.0,
                ),
                path=audio_path,
                source_duration=5,
                effective_duration=3,
            ),
        ),
    )
    cache = FalUploadCache(tmp_path / "cache")
    first = upload_manifest_media(inspection, uploader=uploader, cache=cache)
    second = upload_manifest_media(inspection, uploader=uploader, cache=cache)

    assert first == second
    assert len(uploads) == 2
    assert {call["operation"] for call in calls} == {"remove_audio", "trim_audio"}
    assert all("processed" in path for path in uploads)
    cache_path = tmp_path / "cache" / "upload_cache_v1.json"
    cache_text = cache_path.read_text(encoding="utf-8")
    cache_data = json.loads(cache_text)
    sources = [entry["source"] for entry in cache_data["entries"].values()]
    assert str(video_path.resolve()) in {source["absolute_path"] for source in sources}
    assert all("file_size" in source and "mtime_ns" in source for source in sources)
    assert any(source["transform"].get("trim_start") == 1.0 for source in sources)


def test_cache_key_changes_with_file_identity(tmp_path):
    source = tmp_path / "image.png"
    source.write_bytes(b"one")
    cache = FalUploadCache(tmp_path / "cache")
    uploads = []

    def uploader(path):
        uploads.append(path)
        return f"https://storage.example/{len(uploads)}"

    first = cache.upload(source, transform=None, uploader=uploader)
    source.write_bytes(b"different-size")
    second = cache.upload(source, transform=None, uploader=uploader)
    assert first != second
    assert len(uploads) == 2


def test_upload_cache_records_preprocess_and_upload_wall_time(tmp_path, monkeypatch):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")

    def fake_preprocess(source_path, destination, transform):
        time.sleep(0.001)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
        return destination

    def uploader(path):
        time.sleep(0.001)
        return "https://storage.example/video.mp4"

    monkeypatch.setattr(fal_media, "preprocess_media", fake_preprocess)
    timing = {}
    FalUploadCache(tmp_path / "cache").upload(
        source,
        transform={"operation": "remove_audio", "version": 1},
        uploader=uploader,
        timing=timing,
    )
    assert timing["media_prepare_seconds"] > 0
    assert timing["upload_seconds"] > 0


def test_legacy_and_cloud_paths_share_the_same_upload_cache_entry(input_directory, tmp_path):
    media = input_directory / "shared" / "first.png"
    media.parent.mkdir()
    media.write_bytes(b"same-image")
    legacy_manifest = {
        "schema_version": 1,
        "input_prompt": "legacy",
        "conditioned_prompt": "legacy conditioned",
        "main_mode": "text_keyframes",
        "resolved_task": "i2va",
        "aspect": "adaptive",
        "target": {
            "width": 1280,
            "height": 736,
            "requested_duration_seconds": 5,
            "local_frame_count": 124,
        },
        "first_frame": {"slot": "first_frame", "name": "shared/first.png"},
        "last_frame": None,
        "reference_images": [],
        "reference_videos": [],
        "reference_audios": [],
        "hybrid_audio": None,
    }
    legacy = normalize_video_request({"source_manifest": legacy_manifest})
    cloud = normalize_video_request(
        build_cloud_video_request(
            main_mode="text_keyframes",
            input_prompt="cloud",
            aspect="adaptive",
            duration_seconds=5,
            media_values={"first_frame": "shared/first.png"},
        )
    )
    uploads = []

    def uploader(path):
        uploads.append(path)
        return "https://storage.example/shared.png"

    cache = FalUploadCache(tmp_path / "shared-cache")
    legacy_urls = upload_manifest_media(
        inspect_manifest_media(legacy), uploader=uploader, cache=cache
    )
    cloud_urls = upload_manifest_media(
        inspect_manifest_media(cloud), uploader=uploader, cache=cache
    )
    assert legacy_urls.first_frame == cloud_urls.first_frame
    assert len(uploads) == 1
