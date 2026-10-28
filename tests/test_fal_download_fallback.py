from __future__ import annotations

import logging
import types

from hutx_minimax_h3_testpkg import fal_h3_max
from hutx_minimax_h3_testpkg.fal_api_client import FalQueueResult
from hutx_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
from hutx_minimax_h3_testpkg.gh_video_request import normalize_video_request


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "input_prompt": "a cloud passing over a mountain",
        "conditioned_prompt": "a cloud passing over a mountain",
        "main_mode": "text_keyframes",
        "resolved_task": "t2va",
        "aspect": "16:9",
        "target": {
            "width": 1280,
            "height": 736,
            "requested_duration_seconds": 5.0,
            "local_frame_count": 121,
            "local_duration_seconds": 5.0,
        },
        "first_frame": None,
        "last_frame": None,
        "reference_images": [],
        "reference_videos": [],
        "reference_audios": [],
        "hybrid_audio": None,
    }


def test_download_uses_httpx_stream_redirects_and_browser_user_agent(tmp_path, monkeypatch):
    calls: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def raise_for_status(self):
            calls["raise_for_status"] = True

        def iter_bytes(self, *, chunk_size):
            calls["chunk_size"] = chunk_size
            yield b"first"
            yield b""
            yield b"second"

    class FakeClient:
        def __init__(self, **kwargs):
            calls["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def stream(self, method, url):
            calls["stream"] = (method, url)
            return FakeResponse()

    def fake_import_module(name):
        if name == "folder_paths":
            return types.SimpleNamespace(get_output_directory=lambda: str(tmp_path))
        if name == "httpx":
            return types.SimpleNamespace(Client=FakeClient)
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(fal_h3_max.importlib, "import_module", fake_import_module)

    destination = fal_h3_max._download_video(
        "https://cdn.example/video.mp4",
        "request/with unsafe characters",
    )

    assert destination == tmp_path / "fal_h3_max_request_with_unsafe_characters.mp4"
    assert destination.read_bytes() == b"firstsecond"
    assert calls["stream"] == ("GET", "https://cdn.example/video.mp4")
    assert calls["raise_for_status"] is True
    assert calls["chunk_size"] == 1024 * 1024
    client_kwargs = calls["client_kwargs"]
    assert client_kwargs["timeout"] == 60
    assert client_kwargs["follow_redirects"] is True
    assert "Mozilla/5.0" in client_kwargs["headers"]["User-Agent"]


def test_remote_success_download_failure_returns_recoverable_outputs(monkeypatch, caplog):
    class FakeClient:
        def upload_file(self, path):
            raise AssertionError("T2V must not upload media")

        def submit_and_wait(self, endpoint, payload, *, on_submitted=None):
            if on_submitted:
                on_submitted("paid-request-10061")
            return FalQueueResult(
                request_id="paid-request-10061",
                result={
                    "video": {"url": "https://cdn.example/paid-result.mp4"},
                    "expanded_prompt": "server expanded prompt",
                    "seed": 123,
                    "timings": {"inference": 0.74},
                },
            )

    monkeypatch.setattr(fal_h3_max, "FalApiClient", FakeClient)
    monkeypatch.setattr(
        fal_h3_max,
        "_download_video",
        lambda url, request_id: (_ for _ in ()).throw(
            ConnectionRefusedError(10061, "connection refused")
        ),
    )

    with caplog.at_level(logging.ERROR):
        result = FalH3MaxService().run(
            normalize_video_request({"source_manifest": _manifest()}),
            execution_mode="generate",
            resolution="480P",
            prompt_expansion_mode="balanced",
            seed=-1,
            enable_safety_checker=True,
        )

    assert result.local_video_path is None
    assert result.video_url == "https://cdn.example/paid-result.mp4"
    assert result.request_id == "paid-request-10061"
    assert result.expanded_prompt == "server expanded prompt"
    assert "status: generation_succeeded_remote_download_failed" in result.report
    assert "video_url: https://cdn.example/paid-result.mp4" in result.report
    assert "request_id: paid-request-10061" in result.report
    assert "server_inference_seconds: 0.740000s" in result.report
    assert "remote_generation: succeeded" in result.report
    assert "local_download: failed" in result.report
    assert "connection refused" in result.report
    assert "recovery: use video_url directly" in result.report
    assert "Generation completed successfully." in caplog.text
    assert "Remote generation has already succeeded" in caplog.text
    assert "paid-request-10061" in caplog.text
    assert "https://cdn.example/paid-result.mp4" in caplog.text


def test_failed_http_download_removes_partial_file(tmp_path, monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self, *, chunk_size):
            yield b"partial"
            raise ConnectionRefusedError(10061, "connection refused")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def stream(self, method, url):
            return FakeResponse()

    def fake_import_module(name):
        if name == "folder_paths":
            return types.SimpleNamespace(get_output_directory=lambda: str(tmp_path))
        if name == "httpx":
            return types.SimpleNamespace(Client=FakeClient)
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(fal_h3_max.importlib, "import_module", fake_import_module)

    try:
        fal_h3_max._download_video("https://cdn.example/video.mp4", "failed")
    except ConnectionRefusedError:
        pass
    else:
        raise AssertionError("the simulated connection failure must propagate to the service")

    assert not (tmp_path / "fal_h3_max_failed.mp4.part").exists()
    assert not (tmp_path / "fal_h3_max_failed.mp4").exists()
