from __future__ import annotations

import importlib
import re
import time
import types
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg import fal_h3_max
from hutx_minimax_h3_testpkg.fal_api_client import (
    FalApiClient,
    FalConfigurationError,
    FalQueueResult,
)
from hutx_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
from hutx_minimax_h3_testpkg.fal_media import InspectedMedia, MediaInspection
from hutx_minimax_h3_testpkg.fal_models import FalMediaUrls, FalValidationError
from hutx_minimax_h3_testpkg.gh_video_request import (
    NormalizedMediaEntry,
    normalize_video_request,
)
from hutx_minimax_h3_testpkg.fal_router import (
    IMAGE_ENDPOINT,
    REFERENCE_ENDPOINT,
    TEXT_ENDPOINT,
    build_fal_plan,
)


def manifest(task="t2va", **updates):
    value = {
        "schema_version": 1,
        "input_prompt": "raw prompt",
        "conditioned_prompt": "conditioned prompt",
        "main_mode": "all_reference" if task == "ref2va" else "text_keyframes",
        "resolved_task": task,
        "aspect": "16:9",
        "target": {
            "width": 1024,
            "height": 576,
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
    return value


def plan(value):
    return build_fal_plan(
        normalize_video_request({"source_manifest": value}),
        execution_mode="dry_run",
        resolution="768P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )


def test_t2v_route_and_payload():
    result = plan(manifest())
    assert result.endpoint == TEXT_ENDPOINT
    assert result.payload["aspect_ratio"] == "16:9"
    assert "image_url" not in result.payload
    assert "seed" not in result.payload


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1280, 736, "16:9"),
        (736, 1280, "9:16"),
        (960, 544, "16:9"),
        (544, 960, "9:16"),
        (1024, 1024, "1:1"),
    ],
)
def test_t2v_adaptive_canvas_uses_nearest_ratio_with_relative_tolerance(
    width, height, expected
):
    value = manifest("t2va", aspect="adaptive")
    value["target"].update({"width": width, "height": height})
    assert plan(value).payload["aspect_ratio"] == expected


@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_explicit_supported_aspect_is_preserved(aspect):
    value = manifest("t2va", aspect=aspect)
    # Deliberately contradictory canvas proves that explicit aspect wins.
    value["target"].update({"width": 1024, "height": 1024})
    assert plan(value).payload["aspect_ratio"] == aspect


def test_t2v_adaptive_unknown_ratio_outside_tolerance_is_explicit_error():
    value = manifest("t2va", aspect="adaptive")
    value["target"].update({"width": 1000, "height": 500})
    with pytest.raises(FalValidationError) as error:
        plan(value)
    message = str(error.value)
    assert "Adaptive local canvas 1000x500" in message
    assert "local ratio 2.000000" in message
    assert "Nearest fal ratio is 16:9" in message
    assert "difference 12.50%" in message
    assert "Select a fal-supported aspect ratio explicitly" in message


def test_i2v_and_fl2v_route_to_image_endpoint():
    first = {"slot": "first_frame", "name": "first.png"}
    last = {"slot": "last_frame", "name": "last.png"}
    i2v = plan(manifest("i2va", first_frame=first, conditioned_prompt="use Picture 1"))
    assert i2v.endpoint == IMAGE_ENDPOINT
    assert i2v.payload["image_url"].endswith("first.png")
    assert "end_image_url" not in i2v.payload
    assert "aspect_ratio" not in i2v.payload
    assert i2v.payload["prompt"] == "use the first frame"

    fl2v = plan(
        manifest(
            "fl2va",
            first_frame=first,
            last_frame=last,
            conditioned_prompt="from picture 1 to picture 2",
        )
    )
    assert fl2v.endpoint == IMAGE_ENDPOINT
    assert fl2v.payload["end_image_url"].endswith("last.png")
    assert "aspect_ratio" not in fl2v.payload
    assert fl2v.payload["prompt"] == "from the first frame to the last frame"


def test_reference_route_and_reference_limit():
    images = [
        {"slot": f"ref_image_{index}", "name": f"{index}.png"}
        for index in range(1, 10)
    ]
    videos = [
        {"slot": f"ref_video_{index}", "name": f"{index}.mp4", "muted": True}
        for index in range(1, 4)
    ]
    ok = plan(manifest("ref2va", aspect="adaptive", reference_images=images, reference_videos=videos))
    assert ok.endpoint == REFERENCE_ENDPOINT
    assert ok.payload["aspect_ratio"] == "adaptive"
    assert len(ok.payload["reference_image_urls"]) == 9
    assert len(ok.payload["reference_video_urls"]) == 3

    with pytest.raises(FalValidationError, match="at most 12"):
        plan(
            manifest(
                "ref2va",
                aspect="adaptive",
                reference_images=images,
                reference_videos=videos,
                reference_audios=[
                    {"slot": "ref_audio_1", "name": "one.wav", "trim_start": 0, "trim_end": None}
                ],
            )
        )


def test_audio_only_and_l2v_are_explicit_errors():
    with pytest.raises(FalValidationError, match="does not allow audio"):
        plan(
            manifest(
                "ref2va",
                reference_audios=[
                    {"slot": "ref_audio_1", "name": "a.wav", "trim_start": 0, "trim_end": None}
                ],
            )
        )
    with pytest.raises(FalValidationError) as error:
        plan(manifest("l2va", last_frame={"slot": "last_frame", "name": "last.png"}))
    assert str(error.value) == (
        "MiniMax H3 Max 当前未实现 Last-Frame-only 路由。\n"
        "请使用本地 H3 或其他明确支持 L2V 的模型。"
    )


def test_hybrid_audio_is_not_guessed():
    with pytest.raises(FalValidationError, match="Hybrid audio"):
        plan(
            manifest(
                "i2va",
                first_frame={"slot": "first_frame", "name": "first.png"},
                hybrid_audio={"slot": "hybrid_audio", "name": "a.wav"},
            )
        )


def test_dry_run_needs_neither_fal_key_nor_sdk(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    result = FalH3MaxService().run(
        normalize_video_request({"source_manifest": manifest()}),
        execution_mode="dry_run",
        resolution="480P",
        prompt_expansion_mode="quality",
        seed=42,
        enable_safety_checker=False,
    )
    assert result.local_video_path is None
    assert result.endpoint == TEXT_ENDPOINT
    assert result.payload["seed"] == 42


def test_sdk_is_lazy_and_generate_requires_environment_key(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    called = False

    def forbidden_import(name):
        nonlocal called
        called = True
        return importlib.import_module(name)

    module = importlib.import_module("hutx_minimax_h3_testpkg.fal_api_client")
    monkeypatch.setattr(module.importlib, "import_module", forbidden_import)
    with pytest.raises(FalConfigurationError, match="FAL_KEY"):
        FalApiClient()
    assert called is False


def test_missing_sdk_error_is_scoped_to_fal_execution(monkeypatch):
    module = importlib.import_module("hutx_minimax_h3_testpkg.fal_api_client")
    monkeypatch.setenv("FAL_KEY", "test-only")

    def missing(name):
        raise ModuleNotFoundError("No module named 'fal_client'", name="fal_client")

    monkeypatch.setattr(module.importlib, "import_module", missing)
    with pytest.raises(FalConfigurationError) as error:
        FalApiClient()
    assert str(error.value) == "fal-client is not installed."


def test_official_sdk_wrapper_keeps_queue_request_id(monkeypatch):
    module = importlib.import_module("hutx_minimax_h3_testpkg.fal_api_client")
    monkeypatch.setenv("FAL_KEY", "test-only")

    class Handle:
        request_id = "queue-id-7"

        @staticmethod
        def get():
            return {"video": {"url": "https://video.example/result.mp4"}}

    fake_sdk = types.SimpleNamespace(
        upload_file=lambda path: "https://storage.example/file",
        submit=lambda endpoint, arguments: Handle(),
    )
    fake_sdk.SyncClient = lambda key: fake_sdk
    monkeypatch.setattr(module.importlib, "import_module", lambda name: fake_sdk)
    client = FalApiClient()
    submitted = []
    queued = client.submit_and_wait(
        TEXT_ENDPOINT,
        {"prompt": "test"},
        on_submitted=submitted.append,
    )
    assert submitted == ["queue-id-7"]
    assert queued.request_id == "queue-id-7"
    assert queued.result["video"]["url"].endswith("result.mp4")


def test_generate_orchestration_uses_queue_result_without_real_request(tmp_path, monkeypatch):
    calls = []

    class FakeClient:
        def upload_file(self, path):
            raise AssertionError("T2V must not upload media")

        def submit_and_wait(self, endpoint, payload, *, on_submitted=None):
            calls.append((endpoint, payload))
            if on_submitted:
                on_submitted("request-123")
            return FalQueueResult(
                request_id="request-123",
                result={
                    "video": {"url": "https://video.example/result.mp4"},
                    "expanded_prompt": "server expanded prompt",
                    "seed": 987654,
                    "timings": {"inference": 6.25},
                },
            )

    destination = tmp_path / "result.mp4"
    destination.write_bytes(b"mp4")
    monkeypatch.setattr(fal_h3_max, "FalApiClient", FakeClient)
    monkeypatch.setattr(fal_h3_max, "_download_video", lambda url, request_id: destination)

    result = FalH3MaxService().run(
        normalize_video_request({"source_manifest": manifest()}),
        execution_mode="generate",
        resolution="768P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )
    assert calls[0][0] == TEXT_ENDPOINT
    assert calls[0][1]["prompt"] == "conditioned prompt"
    assert result.request_id == "request-123"
    assert result.video_url == "https://video.example/result.mp4"
    assert result.local_video_path == str(destination)
    assert result.expanded_prompt == "server expanded prompt"
    assert (
        "SERVER EXPANDED PROMPT\n==============================\n"
        "server_expanded_prompt:\nserver expanded prompt"
    ) in result.report
    assert "input_prompt: raw prompt" in result.report
    assert "router_prompt: conditioned prompt" in result.report
    assert "returned_seed: 987654" in result.report
    submit_match = re.search(r"fal_submit_to_result_seconds: ([0-9.]+)s", result.report)
    assert submit_match is not None and float(submit_match.group(1)) > 0
    assert "fal_queue_wait_seconds" not in result.report
    assert "server_inference_seconds: 6.250000s" in result.report


def test_generation_success_download_failure_preserves_remote_recovery_details(
    monkeypatch, caplog
):
    class FakeClient:
        def upload_file(self, path):
            raise AssertionError("T2V must not upload media")

        def submit_and_wait(self, endpoint, payload, *, on_submitted=None):
            if on_submitted:
                on_submitted("paid-request-456")
            return FalQueueResult(
                request_id="paid-request-456",
                result={
                    "video": {"url": "https://video.example/paid-result.mp4"},
                    "expanded_prompt": "paid expanded prompt",
                    "seed": 7,
                    "timings": {"inference": 0.7435292259979178},
                },
            )

    monkeypatch.setattr(fal_h3_max, "FalApiClient", FakeClient)
    monkeypatch.setattr(
        fal_h3_max,
        "_download_video",
        lambda url, request_id: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = FalH3MaxService().run(
        normalize_video_request({"source_manifest": manifest()}),
        execution_mode="generate",
        resolution="768P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )

    assert result.local_video_path is None
    assert result.request_id == "paid-request-456"
    assert result.video_url == "https://video.example/paid-result.mp4"
    assert "status: generation_succeeded_remote_download_failed" in result.report
    assert "request_id: paid-request-456" in result.report
    assert "video_url: https://video.example/paid-result.mp4" in result.report
    assert "fal generation failed" not in result.report.lower()
    assert "paid-request-456" in caplog.text
    assert "fal_submit_to_result_seconds:" in caplog.text
    assert "fal_queue_wait_seconds" not in caplog.text
    assert "Generation completed successfully." in caplog.text
    assert "local download failed" in caplog.text
    assert "server_inference_seconds: 0.743529s" in result.report
    assert "fal_node_elapsed_seconds:" in result.report
    assert "download_seconds:" in result.report
    assert "paid expanded prompt" in result.report


def test_optional_output_metadata_is_appended_only_when_present():
    assert fal_h3_max._result_metadata({}) == ("", None, None)
    assert fal_h3_max._result_metadata(
        {
            "expanded_prompt": "expanded by server",
            "seed": 0,
            "timings": {"inference": 0.0},
        }
    ) == ("expanded by server", 0, 0.0)


def test_missing_server_expanded_prompt_returns_empty_output(tmp_path, monkeypatch):
    class FakeClient:
        def upload_file(self, path):
            raise AssertionError("T2V must not upload media")

        def submit_and_wait(self, endpoint, payload, *, on_submitted=None):
            if on_submitted:
                on_submitted("request-no-expanded-prompt")
            return FalQueueResult(
                request_id="request-no-expanded-prompt",
                result={"video": {"url": "https://video.example/no-prompt.mp4"}},
            )

    destination = tmp_path / "result.mp4"
    destination.write_bytes(b"mp4")
    monkeypatch.setattr(fal_h3_max, "FalApiClient", FakeClient)
    monkeypatch.setattr(fal_h3_max, "_download_video", lambda url, request_id: destination)
    result = FalH3MaxService().run(
        normalize_video_request({"source_manifest": manifest()}),
        execution_mode="generate",
        resolution="480P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )
    assert result.expanded_prompt == ""
    assert "SERVER EXPANDED PROMPT\n==============================\nserver_expanded_prompt:\n\n" in result.report


def test_fal_node_elapsed_is_positive_in_dry_run():
    result = FalH3MaxService().run(
        normalize_video_request({"source_manifest": manifest()}),
        execution_mode="dry_run",
        resolution="480P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )
    match = re.search(r"fal_node_elapsed_seconds: ([0-9.]+)s", result.report)
    assert match is not None
    assert float(match.group(1)) > 0


def test_upload_and_download_phase_timings_are_reported(tmp_path, monkeypatch):
    first = InspectedMedia(
        item=NormalizedMediaEntry(slot="first_frame", name="first.png"),
        path=Path("first.png"),
    )
    monkeypatch.setattr(
        fal_h3_max,
        "inspect_manifest_media",
        lambda value: MediaInspection(first, None, (), (), ()),
    )

    def fake_upload(inspection, *, uploader, cache, timing):
        timing["media_prepare_seconds"] += 0.125
        timing["upload_seconds"] += 0.25
        return FalMediaUrls(first_frame="https://storage.example/first.png")

    class FakeClient:
        def upload_file(self, path):
            return "https://storage.example/unused"

        def submit_and_wait(self, endpoint, payload, *, on_submitted=None):
            if on_submitted:
                on_submitted("timed-request")
            return FalQueueResult(
                request_id="timed-request",
                result={
                    "video": {"url": "https://video.example/timed.mp4"},
                    "timings": {"inference": 0.5},
                },
            )

    destination = tmp_path / "timed.mp4"
    destination.write_bytes(b"mp4")

    def fake_download(url, request_id):
        time.sleep(0.002)
        return destination

    monkeypatch.setattr(fal_h3_max, "upload_manifest_media", fake_upload)
    monkeypatch.setattr(fal_h3_max, "FalApiClient", FakeClient)
    monkeypatch.setattr(fal_h3_max, "_download_video", fake_download)
    result = FalH3MaxService().run(
        normalize_video_request({
            "source_manifest": manifest(
                "i2va",
                first_frame={"slot": "first_frame", "name": "first.png"},
            )
        }),
        execution_mode="generate",
        resolution="480P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )
    assert "upload_seconds: 0.250000s" in result.report
    assert "server_inference_seconds: 0.500000s" in result.report
    match = re.search(r"download_seconds: ([0-9.]+)s", result.report)
    assert match is not None and float(match.group(1)) > 0
    match = re.search(r"media_prepare_seconds: ([0-9.]+)s", result.report)
    assert match is not None and float(match.group(1)) >= 0.125
