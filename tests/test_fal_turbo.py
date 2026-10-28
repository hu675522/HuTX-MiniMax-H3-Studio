from __future__ import annotations

import copy
import importlib
import inspect
import itertools
import json
import re
import sys
import types
from datetime import date
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg import fal_h3_max, fal_media
from hutx_minimax_h3_testpkg.fal_api_client import FalQueueResult
from hutx_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
from hutx_minimax_h3_testpkg.fal_media import FalUploadCache, InspectedMedia, MediaInspection
from hutx_minimax_h3_testpkg.fal_models import (
    H3_MODEL_REGISTRY,
    H3_PRICING_REGISTRY,
    FalValidationError,
    estimate_h3_max_cost,
    format_h3_max_cost_report,
    resolve_h3_endpoint,
)
from hutx_minimax_h3_testpkg.fal_router import build_fal_plan
from hutx_minimax_h3_testpkg.gh_video_request import (
    build_cloud_video_request,
    normalize_video_request,
)


OPTIONS = dict(
    execution_mode="dry_run", resolution="480P", prompt_expansion_mode="balanced",
    seed=-1, enable_safety_checker=True,
)
TURBO = "H3 Max Turbo"
ROOT = Path(__file__).resolve().parents[1]


def cloud_request(task="t2v"):
    media = {
        "t2v": {},
        "i2v": {"first_frame": "frames/first.png"},
        "fl2v": {"first_frame": "frames/first.png", "last_frame": "frames/last.png"},
        "l2v": {"last_frame": "frames/last.png"},
        "ref2v": {"ref_image_1": "refs/one.png", "ref_image_3": "refs/three.png"},
    }[task]
    prompt = {
        "t2v": "A paper boat crosses a rain-lit puddle.",
        "i2v": "Animate <Picture 1> with a slow camera push.",
        "fl2v": "Move from <Picture 1> to <Picture 2>.",
        "l2v": "Arrive at the ending frame.",
        "ref2v": "Blend <Picture 1> with <Picture 2>.",
    }[task]
    return build_cloud_video_request(
        main_mode="all_reference" if task == "ref2v" else "text_keyframes",
        input_prompt=prompt, aspect="adaptive", duration_seconds=5, media_values=media,
    )


@pytest.mark.parametrize("task", ["t2v", "i2v", "fl2v"])
def test_turbo_dry_run_payload_matches_published_schema(task, monkeypatch):
    request = normalize_video_request(cloud_request(task))
    monkeypatch.setattr(fal_h3_max, "inspect_manifest_media", lambda _: MediaInspection(None, None, (), (), ()))

    def forbidden(*args, **kwargs):
        raise AssertionError("Dry run must not instantiate the SDK, upload or download")

    monkeypatch.setattr(fal_h3_max, "FalApiClient", forbidden)
    monkeypatch.setattr(fal_h3_max, "upload_manifest_media", forbidden)
    monkeypatch.setattr(fal_h3_max, "_download_video", forbidden)
    result = FalH3MaxService().run(request, **OPTIONS, model_variant=TURBO, pricing_as_of=date(2026, 9, 5))
    max_plan = build_fal_plan(request, **OPTIONS)
    assert result.payload == max_plan.payload
    route = "text-to-video" if task == "t2v" else "image-to-video"
    assert result.endpoint == f"minimax/h3-max-turbo/{route}"
    assert "model: MiniMax H3 Max Turbo" in result.report
    assert "model_variant: H3 Max Turbo" in result.report
    assert "pricing_model: MiniMax H3 Max Turbo" in result.report
    assert "price_per_second: $0.00625 USD" in result.report
    assert "output_video_cost: ~$0.03125 USD" in result.report
    assert result.local_video_path is None and result.expanded_prompt == ""
    common = {"prompt", "duration", "resolution", "prompt_expansion_mode", "enable_safety_checker", "sync_mode"}
    special = {
        "t2v": {"aspect_ratio"}, "i2v": {"image_url"}, "fl2v": {"image_url", "end_image_url"},
    }[task]
    assert set(result.payload) == common | special
    if task == "t2v":
        assert result.payload["aspect_ratio"] == "16:9"
    else:
        assert "aspect_ratio" not in result.payload
        assert "the first frame" in result.payload["prompt"]
        if task == "fl2v":
            assert "the last frame" in result.payload["prompt"]


@pytest.mark.parametrize("task,message", [
    ("ref2v", "H3 Max Turbo 当前没有公开 Reference-to-Video endpoint。\n请切换到 H3 Max 运行 Ref2V。"),
    ("l2v", "MiniMax H3 Max Turbo 当前未实现 Last-Frame-only 路由。\n请使用本地 H3 或其他明确支持 L2V 的模型。"),
])
def test_unsupported_turbo_task_stops_before_media_or_sdk(task, message, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unsupported capability must fail before media or SDK")

    monkeypatch.setattr(fal_h3_max, "inspect_manifest_media", forbidden)
    monkeypatch.setattr(fal_h3_max, "FalApiClient", forbidden)
    with pytest.raises(FalValidationError) as exc:
        FalH3MaxService().run(normalize_video_request(cloud_request(task)), **OPTIONS, model_variant=TURBO)
    assert str(exc.value) == message


@pytest.mark.parametrize("task", ["t2v", "i2v", "fl2v"])
@pytest.mark.parametrize("resolution,rate,standard", [("480P", 0.00625, 0.025), ("768P", 0.01, 0.04)])
def test_turbo_endpoint_pricing_and_inclusive_expiry(task, resolution, rate, standard):
    endpoint = resolve_h3_endpoint(TURBO, task)
    for as_of, expected_rate, pricing_type in [
        (date(2026, 9, 5), rate, "promotion"),
        (date(2026, 9, 7), rate, "promotion"),
        (date(2026, 9, 8), standard, "standard_after_promotion"),
    ]:
        estimate = estimate_h3_max_cost(
            endpoint=endpoint, resolved_task=task, output_duration_seconds=5,
            resolution=resolution, as_of=as_of,
        )
        assert estimate.pricing_model == "MiniMax H3 Max Turbo"
        assert estimate.price_per_second == pytest.approx(expected_rate)
        assert estimate.estimated_total_cost == pytest.approx(5 * expected_rate)
        assert estimate.reference_estimated_cost == 0
        assert estimate.pricing_type == pricing_type


def test_turbo_model_aware_price_without_endpoint_and_max_price_regression():
    for variant, cost in [("H3 Max", 0.0625), (TURBO, 0.03125)]:
        estimate = estimate_h3_max_cost(
            model_variant=variant, resolved_task="i2v", output_duration_seconds=5,
            resolution="480P", as_of=date(2026, 9, 5),
        )
        assert estimate.output_video_cost == pytest.approx(cost)
    for task in ("t2v", "i2v"):
        assert H3_PRICING_REGISTRY["H3 Max"][resolve_h3_endpoint("H3 Max", task).rsplit("/", 1)[-1]] is not (
            H3_PRICING_REGISTRY[TURBO][resolve_h3_endpoint(TURBO, task).rsplit("/", 1)[-1]]
        )


@pytest.mark.parametrize("endpoint,variant,task", [
    ("minimax/h3-max-turbo/reference-to-video", None, "ref2v"),
    ("minimax/h3-max-turbo/image-to-video", "H3 Max", "i2v"),
    (None, TURBO, "ref2v"),
    ("unknown/h3/image-to-video", None, "i2v"),
])
def test_pricing_cannot_fall_back_to_max_for_unknown_or_mismatched_routes(endpoint, variant, task):
    with pytest.raises(FalValidationError):
        estimate_h3_max_cost(
            endpoint=endpoint, model_variant=variant, resolved_task=task,
            output_duration_seconds=5, resolution="480P",
        )


def test_turbo_max_cost_guard_uses_unrounded_estimate_before_upload(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Cost guard must run before SDK and upload")

    monkeypatch.setattr(fal_h3_max, "FalApiClient", forbidden)
    monkeypatch.setattr(fal_h3_max, "upload_manifest_media", forbidden)
    with pytest.raises(FalValidationError, match="request was not submitted") as exc:
        FalH3MaxService().run(
            normalize_video_request(cloud_request()), **{**OPTIONS, "execution_mode": "generate"},
            model_variant=TURBO, max_estimated_cost=0.03124, pricing_as_of=date(2026, 9, 5),
        )
    assert "estimated_total_cost: $0.03125 USD" in str(exc.value)
    assert "max_estimated_cost: $0.03124 USD" in str(exc.value)


def test_same_gh_request_and_optimized_prompt_are_shared_by_both_variants(node_module, monkeypatch):
    module_name = "hutx_minimax_h3_testpkg.cloud_video_nodes"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    cloud_node = importlib.import_module(module_name).GHCloudVideoInputGH
    # The shared frontend optimizer's provider-neutral result enters Cloud once;
    # switching the downstream model must neither re-optimize nor rewrite it.
    optimized = "Move from <Picture 1> to <Picture 2>."
    output = cloud_node.execute(
        main_mode="text_keyframes", prompt="Original user prompt", aspect="adaptive",
        duration_seconds=5, first_frame="frames/first.png", last_frame="frames/last.png",
        optimizer_enabled=True, optimized_prompt=optimized, optimizer_report="mock optimizer report",
    )
    request = output.values[0]
    original = copy.deepcopy(request)
    normalized = normalize_video_request(request)
    plans = [build_fal_plan(normalized, **OPTIONS, model_variant=variant) for variant in H3_MODEL_REGISTRY]
    assert plans[0].payload == plans[1].payload
    assert request == original
    assert request["prompt_tag_scheme"] == "gh_media_v1"
    assert request["input_prompt"] == optimized == output.values[1]
    assert "model_variant" not in request
    assert set(request["metadata"]) == {"source_node"}


def test_max_ref2v_payload_and_reference_billing_regression():
    plan = build_fal_plan(normalize_video_request(cloud_request("ref2v")), **OPTIONS)
    assert plan.endpoint == "minimax/h3-max/reference-to-video"
    assert plan.prompt == "Blend Image 1 with Image 2."
    assert len(plan.payload["reference_image_urls"]) == 2
    estimate = estimate_h3_max_cost(
        endpoint=plan.endpoint, resolved_task="ref2v", output_duration_seconds=5,
        resolution="480P", reference_image_pixels=[1024 * 1024] * 5,
    )
    assert estimate.output_video_cost == pytest.approx(0.25)
    assert estimate.reference_estimated_cost == pytest.approx(0.02048)
    assert estimate.estimated_total_cost == pytest.approx(0.27048)


@pytest.mark.parametrize("expanded_prompt", [None, "Full Turbo server prompt\nsecond line"])
def test_max_and_turbo_share_upload_cache_and_keep_metadata_and_timings(tmp_path, monkeypatch, expanded_prompt):
    ticks = itertools.count(100.0, 0.01)
    clock = types.SimpleNamespace(perf_counter=lambda: next(ticks), time=lambda: 1000.0)
    monkeypatch.setattr(fal_h3_max, "time", clock)
    monkeypatch.setattr(fal_media, "time", clock)
    request = normalize_video_request(cloud_request("i2v"))
    image = tmp_path / "first.png"
    image.write_bytes(b"test-media-identity")
    inspection = MediaInspection(InspectedMedia(request.first_frame, image, width=1024, height=1024), None, (), (), ())
    monkeypatch.setattr(fal_h3_max, "inspect_manifest_media", lambda _: inspection)
    uploads, submissions = [], []

    class FakeClient:
        def upload_file(self, path):
            uploads.append(path)
            return "https://test.invalid/shared-image.png"

        def submit_and_wait(self, endpoint, payload, *, on_submitted):
            submissions.append((endpoint, dict(payload)))
            request_id = f"mock-{len(submissions)}"
            on_submitted(request_id)
            return FalQueueResult(request_id, {
                "video": {"url": "https://test.invalid/video.mp4"},
                "expanded_prompt": expanded_prompt, "seed": 81, "timings": {"inference": 0.42},
            })

    monkeypatch.setattr(fal_h3_max, "FalApiClient", FakeClient)

    def fake_download(url, request_id):
        output = tmp_path / f"{request_id}.mp4"
        output.write_bytes(b"mock-video")
        return output

    monkeypatch.setattr(fal_h3_max, "_download_video", fake_download)
    results = []
    for variant in ("H3 Max", TURBO):
        # New cache object forces the second run to read the same persistent cache.
        results.append(FalH3MaxService(upload_cache=FalUploadCache(tmp_path / "cache")).run(
            request, **{**OPTIONS, "execution_mode": "generate"}, model_variant=variant,
            max_estimated_cost=0.10, pricing_as_of=date(2026, 9, 5),
        ))
    assert len(uploads) == 1
    assert [item[0] for item in submissions] == [
        "minimax/h3-max/image-to-video", "minimax/h3-max-turbo/image-to-video",
    ]
    assert submissions[0][1] == submissions[1][1]
    assert "model_variant" not in (tmp_path / "cache" / "upload_cache_v1.json").read_text(encoding="utf-8")
    for result in results:
        assert result.expanded_prompt == (expanded_prompt or "")
        assert "returned_seed: 81" in result.report
        assert "server_inference_seconds: 0.420000s" in result.report
        for field in ("media_prepare_seconds", "download_seconds", "fal_node_elapsed_seconds", "fal_submit_to_result_seconds"):
            assert float(re.search(rf"{field}: ([0-9.]+)s", result.report).group(1)) > 0
        assert "workflow_total_elapsed_seconds:" in result.report
        assert "fal_queue_wait_seconds" not in result.report
    assert float(re.search(r"upload_seconds: ([0-9.]+)s", results[0].report).group(1)) > 0
    assert "upload_seconds: 0.000000s" in results[1].report


@pytest.fixture
def node_module(monkeypatch):
    class FakeNodeOutput:
        def __init__(self, *values, **kwargs):
            self.values = values

    latest = types.ModuleType("comfy_api.latest")
    latest.io = types.SimpleNamespace(ComfyNode=object, Custom=lambda name: name, NodeOutput=FakeNodeOutput)
    latest.ui = types.SimpleNamespace(PreviewText=lambda text: text)
    input_impl = types.ModuleType("comfy_api.latest._input_impl")
    input_impl.VideoFromFile = lambda path: ("VideoFromFile", path)
    monkeypatch.setitem(sys.modules, "comfy_api", types.ModuleType("comfy_api"))
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    monkeypatch.setitem(sys.modules, "comfy_api.latest._input_impl", input_impl)
    module_name = "hutx_minimax_h3_testpkg.fal_nodes"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return importlib.import_module(module_name)


def test_legacy_node_execution_without_variant_defaults_to_max(node_module, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    fixture = json.loads((ROOT / "tests/fixtures/v01_legacy_fal_workflow.json").read_text(encoding="utf-8"))
    case = fixture["extra"]["compatibility_cases"]["t2v"]
    output = node_module.FalH3MaxVideoGH.execute(
        integration={"source_manifest": case["manifest"]}, **OPTIONS, max_estimated_cost=2.0,
    )
    assert output.values[3] == case["expected_endpoint"]
    assert output.values[5] == ""
    assert len(output.values) == 6
    assert inspect.signature(node_module.FalH3MaxVideoGH.execute).parameters["model_variant"].default == "H3 Max"


def test_turbo_node_preserves_six_outputs_and_expanded_prompt(node_module, monkeypatch):
    from hutx_minimax_h3_testpkg.fal_models import FalGenerationResult

    def fake_run(self, request, **kwargs):
        assert kwargs["model_variant"] == TURBO
        return FalGenerationResult("mock.mp4", "https://test.invalid/video.mp4", "mock-request",
                                   "minimax/h3-max-turbo/image-to-video", "mock-report", {}, "expanded")

    monkeypatch.setattr(node_module.FalH3MaxService, "run", fake_run)
    output = node_module.FalH3MaxVideoGH.execute(
        integration=cloud_request("i2v"), **OPTIONS, max_estimated_cost=2.0, model_variant=TURBO,
    )
    assert output.values == (
        ("VideoFromFile", "mock.mp4"), "https://test.invalid/video.mp4", "mock-request",
        "minimax/h3-max-turbo/image-to-video", "mock-report", "expanded",
    )
