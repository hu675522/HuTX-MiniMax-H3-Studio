from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg import fal_h3_max
from hutx_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
from hutx_minimax_h3_testpkg.fal_media import InspectedMedia, MediaInspection
from hutx_minimax_h3_testpkg.fal_models import (
    FalValidationError,
    estimate_h3_max_cost,
)
from hutx_minimax_h3_testpkg.fal_router import (
    IMAGE_ENDPOINT,
    REFERENCE_ENDPOINT,
    TEXT_ENDPOINT,
)
from hutx_minimax_h3_testpkg.gh_video_request import (
    NormalizedMediaEntry,
    normalize_video_request,
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


def empty_inspection() -> MediaInspection:
    return MediaInspection(None, None, (), (), ())


def test_cost_estimate_matches_published_reference_example():
    estimate = estimate_h3_max_cost(
        resolved_task="ref2va",
        endpoint=REFERENCE_ENDPOINT,
        output_duration_seconds=5,
        resolution="768P",
        reference_image_pixels=[1024 * 1024, 1024 * 1024],
        reference_video_seconds=[5],
    )
    assert estimate.output_video_cost == pytest.approx(0.40)
    assert estimate.reference_estimated_tokens == pytest.approx(39344)
    assert estimate.reference_billable_tokens == pytest.approx(35248)
    assert estimate.reference_estimated_cost == pytest.approx(0.70496)
    assert estimate.estimated_total_cost == pytest.approx(1.10496)
    assert estimate.approximate is True
    assert estimate.pricing_endpoint == "reference-to-video"
    assert estimate.pricing_type == "standard_conservative"


def test_i2v_480p_five_second_promotional_cost():
    estimate = estimate_h3_max_cost(
        resolved_task="i2va",
        endpoint=IMAGE_ENDPOINT,
        output_duration_seconds=5,
        resolution="480P",
        as_of=date(2026, 9, 4),
    )
    assert estimate.output_video_cost == pytest.approx(0.0625)
    assert estimate.estimated_total_cost == pytest.approx(0.0625)
    assert estimate.pricing_endpoint == "image-to-video"
    assert estimate.pricing_type == "promotion"


def test_i2v_768p_promotional_cost():
    estimate = estimate_h3_max_cost(
        resolved_task="fl2va",
        endpoint=IMAGE_ENDPOINT,
        output_duration_seconds=5,
        resolution="768P",
        as_of=date(2026, 9, 4),
    )
    assert estimate.output_video_cost == pytest.approx(0.10)


def test_t2v_uses_its_own_endpoint_pricing_entry():
    estimate = estimate_h3_max_cost(
        resolved_task="t2va",
        endpoint=TEXT_ENDPOINT,
        output_duration_seconds=5,
        resolution="480P",
        as_of=date(2026, 9, 4),
    )
    assert estimate.output_video_cost == pytest.approx(0.0625)
    assert estimate.pricing_endpoint == "text-to-video"


def test_promotion_expiry_falls_back_to_standard_rate():
    estimate = estimate_h3_max_cost(
        resolved_task="i2va",
        endpoint=IMAGE_ENDPOINT,
        output_duration_seconds=5,
        resolution="480P",
        as_of=date(2026, 9, 8),
    )
    assert estimate.output_video_cost == pytest.approx(0.25)
    assert estimate.pricing_type == "standard_after_promotion"
    assert estimate.output_approximate is False


def test_ref2v_dry_run_report_includes_reference_cost(monkeypatch):
    first = InspectedMedia(
        item=NormalizedMediaEntry(slot="ref_image_1", name="one.png"),
        path=Path("one.png"),
        width=1024,
        height=1024,
    )
    second = InspectedMedia(
        item=NormalizedMediaEntry(slot="ref_image_2", name="two.png"),
        path=Path("two.png"),
        width=1024,
        height=1024,
    )
    video = InspectedMedia(
        item=NormalizedMediaEntry(
            slot="ref_video_1", name="motion.mp4", muted=True
        ),
        path=Path("motion.mp4"),
        source_duration=5,
        effective_duration=5,
    )
    monkeypatch.setattr(
        fal_h3_max,
        "inspect_manifest_media",
        lambda value: MediaInspection(None, None, (first, second), (video,), ()),
    )
    value = manifest(
        "ref2va",
        conditioned_prompt="Image from Picture 1 and Picture 2 follows Video 1",
        reference_images=[
            {"slot": "ref_image_1", "name": "one.png"},
            {"slot": "ref_image_2", "name": "two.png"},
        ],
        reference_videos=[
            {"slot": "ref_video_1", "name": "motion.mp4", "muted": True}
        ],
    )
    result = FalH3MaxService().run(
        normalize_video_request({"source_manifest": value}),
        execution_mode="dry_run",
        resolution="768P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
        max_estimated_cost=2.0,
    )
    assert "COST" in result.report
    assert "Estimated Cost:" in result.report
    assert "output_video_cost: $0.4000 USD" in result.report
    assert "reference_estimated_cost: ~$0.7050 USD (approximate)" in result.report
    assert "estimated_total_cost: ~$1.1050 USD (approximate)" in result.report
    assert "additional reference billing" not in result.report
    assert "reference_billing_note:" in result.report


def test_max_cost_guard_runs_before_client_or_submit(monkeypatch):
    monkeypatch.setattr(fal_h3_max, "inspect_manifest_media", lambda value: empty_inspection())

    class ForbiddenClient:
        def __init__(self):
            raise AssertionError("client must not be created before the cost guard")

    monkeypatch.setattr(fal_h3_max, "FalApiClient", ForbiddenClient)
    with pytest.raises(FalValidationError) as error:
        FalH3MaxService().run(
            normalize_video_request({"source_manifest": manifest()}),
            execution_mode="generate",
            resolution="768P",
            prompt_expansion_mode="balanced",
            seed=-1,
            enable_safety_checker=True,
            max_estimated_cost=0.09,
            pricing_as_of=date(2026, 9, 4),
        )
    assert "request was not submitted" in str(error.value)
    assert "estimated_total_cost: $0.1000 USD" in str(error.value)
    assert "max_estimated_cost: $0.0900 USD" in str(error.value)


def test_dry_run_reports_cost_even_when_it_exceeds_generate_guard(monkeypatch):
    monkeypatch.setattr(fal_h3_max, "inspect_manifest_media", lambda value: empty_inspection())
    result = FalH3MaxService().run(
        normalize_video_request({"source_manifest": manifest()}),
        execution_mode="dry_run",
        resolution="768P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
        max_estimated_cost=0.01,
        pricing_as_of=date(2026, 9, 4),
    )
    assert "estimated_total_cost: ~$0.1000 USD" in result.report
    assert "max_estimated_cost: $0.0100 USD" in result.report
