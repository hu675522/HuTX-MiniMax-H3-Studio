from __future__ import annotations

import importlib.metadata
import json
import logging
import socket
import traceback
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import fal_client
import fal_client.client as sdk_module

from hutx_minimax_h3_testpkg import fal_h3_max, fal_media, fal_upload
from hutx_minimax_h3_testpkg.fal_api_client import FalApiClient
from hutx_minimax_h3_testpkg.fal_media import FalUploadCache, InspectedMedia, MediaInspection
from hutx_minimax_h3_testpkg.gh_video_request import NormalizedMediaEntry, build_cloud_video_request, normalize_video_request
from hutx_minimax_h3_testpkg.fal_router import build_fal_plan


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real network is forbidden in Unicode upload tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def official_sdk(monkeypatch):
    """The installed ComfyUI SDK, with HTTP transport replaced, not upload_file."""
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.params.get("storage_type") == "gcs":
            return httpx.Response(400, json={"detail": "Invalid storage type"})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={})
        if request.method == "PUT":
            return httpx.Response(200, headers={"etag": "mock-etag"})
        if request.url.path.endswith("/multipart"):
            return httpx.Response(200, json={"access_url": "https://mock.invalid/object", "uploadId": "mock-upload"})
        return httpx.Response(200, json={"access_url": f"https://mock.invalid/file/{len(requests)}"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        monkeypatch.setattr(fal_client.SyncClient, "_get_cdn_client", lambda self: transport)
        token = SimpleNamespace(token_type="Bearer", token="TEST_UPLOAD_TOKEN", base_upload_url="https://mock.invalid")
        monkeypatch.setattr(sdk_module.CDNTokenManager, "get_token", lambda self: token)
        monkeypatch.setenv("FAL_KEY", "TEST_FAL_KEY")
        client = FalApiClient()
        object.__setattr__(client._sdk, "_client", transport)
        yield client, requests


def test_current_sdk_reproduces_unicode_header_before_transport(tmp_path, official_sdk):
    client, requests = official_sdk
    source = tmp_path / "中文文件名.png"
    source.write_bytes(b"mock image")
    assert importlib.metadata.version("fal-client") == "1.0.1"
    with pytest.raises(UnicodeEncodeError) as error:
        client._sdk.upload_file(source, repository="fal_v3", fallback_repository=[])
    assert error.value.encoding == "ascii"
    assert error.value.object == source.name
    assert "_normalize_header_value" in "".join(traceback.format_exception(error.value))
    assert requests == []


def test_old_default_fallback_masks_filename_error_with_gcs(tmp_path, official_sdk, caplog):
    client, requests = official_sdk
    source = tmp_path / "中文文件名.png"
    source.write_bytes(b"image")
    with pytest.raises(Exception, match="Invalid storage type"):
        client._sdk.upload_file(source)
    assert "falling back to fal" in caplog.text
    assert "ascii" in caplog.text
    assert len(requests) == 1 and requests[0].url.params["storage_type"] == "gcs"


@pytest.mark.parametrize("name", ["image.png", "file with spaces.MP4", "参考图.png", "舞蹈参考.mp4", "背景音乐.wav", "首帧 女主.PNG", "画像.jpg", "음악.MP3", "🎬.webp"])
@pytest.mark.parametrize("fails", [False, True])
def test_staging_content_extension_and_cleanup(tmp_path, name, fails):
    original = tmp_path / name
    original.write_bytes(b"unaltered bytes\x00\xff")
    staged = None
    try:
        with fal_upload.prepare_fal_upload_path(original) as staged:
            assert staged.name.isascii()
            assert staged.suffix == original.suffix
            assert staged.read_bytes() == original.read_bytes()
            assert (staged == original) == name.isascii()
            if fails:
                raise RuntimeError("mock failure")
    except RuntimeError:
        assert fails
    assert original.read_bytes() == b"unaltered bytes\x00\xff"
    if staged != original:
        assert not staged.exists() and not staged.parent.exists()


@pytest.mark.parametrize("name", ["参考图.png", "舞蹈参考.mp4", "背景音乐.wav", "😀.png", "file with spaces.png"])
def test_installed_v3_upload_accepts_staging_without_gcs(tmp_path, name, official_sdk):
    client, requests = official_sdk
    source = tmp_path / name
    source.write_bytes(b"mock bytes")
    assert client.upload_file(str(source)).startswith("https://mock.invalid/")
    assert len(requests) == 1
    assert requests[0].headers["X-Fal-File-Name"].isascii()
    assert requests[0].content == source.read_bytes()
    assert "gcs" not in str(requests[0].url)


def test_installed_sdk_multipart_unicode_upload(tmp_path, official_sdk, monkeypatch):
    client, requests = official_sdk
    monkeypatch.setattr(sdk_module, "MULTIPART_THRESHOLD", 1)
    source = tmp_path / "大型中文视频.mp4"
    source.write_bytes(b"multipart data")
    assert client.upload_file(str(source)) == "https://mock.invalid/object"
    assert [req.method for req in requests] == ["POST", "PUT", "POST"]
    assert requests[0].headers["X-Fal-File-Name"].isascii()
    assert requests[1].content == source.read_bytes()
    assert all("gcs" not in str(req.url) for req in requests)


def test_unicode_retry_only_v3_with_fresh_staging_and_cleanup(tmp_path, monkeypatch):
    source = tmp_path / "already-safe.png"
    source.write_bytes(b"bytes")
    attempts = []
    def upload(path, **options):
        path = Path(path)
        attempts.append(path)
        assert options == {"repository": "fal_v3", "fallback_repository": []}
        if len(attempts) == 1:
            raise UnicodeEncodeError("ascii", "中文", 0, 2, "ordinal not in range(128)")
        assert path != source and path.name.startswith("hutx_fal_")
        assert path.read_bytes() == source.read_bytes()
        return "https://mock.invalid/success"
    client = object.__new__(FalApiClient)
    client._sdk = SimpleNamespace(upload_file=upload)
    assert client.upload_file(str(source)).endswith("success")
    assert len(attempts) == 2 and not attempts[-1].exists()


@pytest.mark.parametrize("failure, expected", [
    (UnicodeEncodeError("ascii", "中文", 0, 2, "ordinal not in range(128)"), fal_upload.FalUploadFilenameEncodingError),
    (httpx.ConnectError("TEST_FAL_KEY https://signed.invalid/?token=TEST_UPLOAD_TOKEN"), fal_upload.FalUploadTransportError),
    (RuntimeError("Invalid storage type TEST_FAL_KEY"), fal_upload.FalUploadProviderError),
])
def test_retry_failure_preserves_safe_primary_and_redacts(tmp_path, failure, expected, monkeypatch, caplog):
    source = tmp_path / "参考图.png"
    source.write_bytes(b"mock")
    paths = []
    monkeypatch.setenv("FAL_KEY", "TEST_FAL_KEY")
    def upload(path, **options):
        paths.append(Path(path))
        for name in ("fal_client.client", "httpx", "httpcore.http11"):
            logging.getLogger(name).warning("Authorization: TEST_FAL_KEY Bearer TEST_UPLOAD_TOKEN https://signed.invalid/?token=TEST_UPLOAD_TOKEN")
        if len(paths) == 1:
            raise UnicodeEncodeError("ascii", "中文", 0, 2, "ordinal not in range(128)")
        raise failure
    client = object.__new__(FalApiClient)
    client._sdk = SimpleNamespace(upload_file=upload)
    with pytest.raises(expected) as error:
        client.upload_file(str(source))
    assert "primary: fal_v3 filename encoding failure; retry:" in str(error.value)
    combined = caplog.text + "".join(traceback.format_exception(error.value))
    for secret in ("TEST_FAL_KEY", "TEST_UPLOAD_TOKEN", "https://signed.invalid", "Authorization:"):
        assert secret not in combined
    assert len(paths) == 2 and paths[0] != paths[1]
    assert all(not path.exists() for path in paths)


def test_transport_failure_does_not_retry(tmp_path):
    source = tmp_path / "参考图.png"
    source.write_bytes(b"image")
    calls = []
    def upload(path, **options):
        calls.append(path)
        raise httpx.ConnectError("offline")
    client = object.__new__(FalApiClient)
    client._sdk = SimpleNamespace(upload_file=upload)
    with pytest.raises(fal_upload.FalUploadTransportError):
        client.upload_file(str(source))
    assert len(calls) == 1


def test_cache_identity_hit_zero_time_and_no_staging(tmp_path, monkeypatch):
    source = tmp_path / "参考图.png"
    source.write_bytes(b"image")
    cache = FalUploadCache(tmp_path / "cache")
    calls = []
    def upload(path):
        calls.append(Path(path))
        assert Path(path).name.isascii()
        return "https://mock.invalid/image"
    first = cache.upload(source, transform=None, uploader=upload)
    def forbidden(*args, **kwargs):
        raise AssertionError("Cache hit must not stage")
    monkeypatch.setattr(fal_media, "prepare_fal_upload_path", forbidden)
    timing = {}
    assert FalUploadCache(cache.directory).upload(source, transform=None, uploader=upload, timing=timing) == first
    assert timing["upload_seconds"] == 0 and len(calls) == 1
    assert not calls[0].exists()
    entry = next(iter(json.loads(cache.index_path.read_text(encoding="utf-8"))["entries"].values()))
    assert entry["source"] == cache._key_data(source, {})


def make_request(tmp_path, monkeypatch, mode):
    media = {"first_frame": "中文首帧.png"}
    prompt = "<Picture 1>"
    if mode == "fl2v":
        media["last_frame"] = "中文尾帧.png"
        prompt += "<Picture 2>"
    if mode == "ref2v":
        media = {"ref_image_1": "参考图.png", "ref_image_5": "另一张.png", "ref_video_1": "舞蹈参考.mp4", "ref_audio_3": "背景音乐.wav"}
        prompt = "<Picture 1><Picture 2><Video 1><Audio 1>"
    for name in media.values():
        (tmp_path / name).write_bytes(name.encode("utf-8"))
    monkeypatch.setattr(fal_media, "resolve_input_path", lambda name: tmp_path / name)
    monkeypatch.setattr(fal_media, "probe_image_size", lambda path: (512, 512))
    monkeypatch.setattr(fal_media, "probe_duration", lambda path: 3.0)
    request = normalize_video_request(build_cloud_video_request(
        main_mode="all_reference" if mode == "ref2v" else "text_keyframes",
        input_prompt=prompt, aspect="adaptive", duration_seconds=5, media_values=media,
    ))
    return request


@pytest.mark.parametrize("mode", ["i2v", "fl2v", "ref2v"])
def test_mode_urls_and_canonical_labels_unchanged(tmp_path, monkeypatch, official_sdk, mode):
    client, requests = official_sdk
    request = make_request(tmp_path, monkeypatch, mode)
    inspection = fal_media.inspect_manifest_media(request)
    urls = fal_media.upload_manifest_media(inspection, uploader=client.upload_file, cache=FalUploadCache(tmp_path / "cache"))
    plan = build_fal_plan(request, media_urls=urls, execution_mode="generate", resolution="768P", prompt_expansion_mode="balanced", seed=-1, enable_safety_checker=True)
    assert len(requests) == {"i2v": 1, "fl2v": 2, "ref2v": 4}[mode]
    if mode == "ref2v":
        assert [len(urls.reference_images), len(urls.reference_videos), len(urls.reference_audios)] == [2, 1, 1]
        assert plan.payload["prompt"] == "Image 1Image 2Video 1Audio 1"
        assert plan.payload["reference_image_urls"] == list(urls.reference_images)
        assert plan.payload["reference_video_urls"] == list(urls.reference_videos)
        assert plan.payload["reference_audio_urls"] == list(urls.reference_audios)
        assert request.reference_images[1].slot == "ref_image_5"
        assert request.reference_audios[0].name == "背景音乐.wav"
    else:
        assert plan.payload["image_url"] == urls.first_frame
        if mode == "fl2v":
            assert plan.payload["end_image_url"] == urls.last_frame != urls.first_frame


def test_hybrid_audio_staging_is_shared_without_enabling_unsupported_router(tmp_path, caplog):
    source = tmp_path / "背景音乐.wav"
    source.write_bytes(b"sound")
    item = InspectedMedia(NormalizedMediaEntry(slot="hybrid_audio", name=source.name), source)
    inspection = MediaInspection(None, None, (), (), (item,))
    with caplog.at_level(logging.INFO):
        urls = fal_media.upload_manifest_media(inspection, uploader=lambda path: "https://mock.invalid/audio", cache=FalUploadCache(tmp_path / "cache"))
    assert len(urls.reference_audios) == 1
    assert '"kind": "hybrid_audio"' in caplog.text
    assert '"mime_type": "audio/' in caplog.text


@pytest.mark.parametrize("mode", ["i2v", "fl2v", "ref2v"])
def test_failed_upload_never_submits_generation(tmp_path, monkeypatch, mode, caplog):
    request = make_request(tmp_path, monkeypatch, mode)
    paths = []
    submitted = []
    def upload(path, **options):
        paths.append(Path(path))
        raise UnicodeEncodeError("ascii", "中文", 0, 2, "ordinal not in range(128)")
    client = object.__new__(FalApiClient)
    client._sdk = SimpleNamespace(upload_file=upload, submit=lambda *args, **kwargs: submitted.append(args))
    monkeypatch.setattr(fal_h3_max, "FalApiClient", lambda: client)
    with pytest.raises(fal_upload.FalUploadFilenameEncodingError):
        fal_h3_max.FalH3MaxService(upload_cache=FalUploadCache(tmp_path / "cache")).run(
            request, execution_mode="generate", resolution="768P", prompt_expansion_mode="balanced", seed=-1, enable_safety_checker=True, max_estimated_cost=100,
        )
    assert len(paths) == 2 and not submitted
    assert all(not path.exists() for path in paths)
    assert "Fal upload item failed:" in caplog.text
    assert '"basename_contains_non_ascii": true' in caplog.text
    assert '"slot": "ref_image_1"' in caplog.text if mode == "ref2v" else '"slot": "first_frame"' in caplog.text
    assert '"extension": ".png"' in caplog.text
    assert '"upload_basename": "hutx_fal_' in caplog.text
    assert '"mime_type": "image/png"' in caplog.text
    assert not (tmp_path / "cache" / "upload_cache_v1.json").exists()
    assert "参考图" not in caplog.text


def test_upload_retry_success_submits_generation_exactly_once(tmp_path, monkeypatch):
    request = make_request(tmp_path, monkeypatch, "i2v")
    uploads, submissions = [], []
    def upload(path, **options):
        uploads.append(path)
        if len(uploads) == 1:
            raise UnicodeEncodeError("ascii", "中文", 0, 2, "ordinal not in range(128)")
        return "https://mock.invalid/image"
    class Handle:
        request_id = "mock-request"
        def get(self):
            return {"video": {"url": "https://mock.invalid/video"}}
    def submit(endpoint, arguments):
        submissions.append(endpoint)
        return Handle()
    client = object.__new__(FalApiClient)
    client._sdk = SimpleNamespace(upload_file=upload, submit=submit)
    monkeypatch.setattr(fal_h3_max, "FalApiClient", lambda: client)
    monkeypatch.setattr(fal_h3_max, "_download_video", lambda *args: tmp_path / "mock.mp4")
    result = fal_h3_max.FalH3MaxService(upload_cache=FalUploadCache(tmp_path / "cache")).run(
        request, execution_mode="generate", resolution="768P", prompt_expansion_mode="balanced", seed=-1, enable_safety_checker=True,
    )
    assert len(uploads) == 2 and len(submissions) == 1
    assert result.request_id == "mock-request"
