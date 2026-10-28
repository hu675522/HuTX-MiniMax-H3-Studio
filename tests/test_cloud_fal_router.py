from __future__ import annotations

import pytest

from hutx_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
from hutx_minimax_h3_testpkg.fal_models import FalValidationError
from hutx_minimax_h3_testpkg.fal_router import (
    IMAGE_ENDPOINT,
    REFERENCE_ENDPOINT,
    TEXT_ENDPOINT,
    adapt_prompt_for_fal,
    build_fal_plan,
)
from hutx_minimax_h3_testpkg.gh_video_request import (
    build_cloud_video_request,
    normalize_cloud_request,
)


EMPTY_MEDIA = {
    "first_frame": "",
    "last_frame": "",
    "hybrid_audio": "",
    **{f"ref_image_{index}": "" for index in range(1, 10)},
    **{f"ref_video_{index}": "" for index in range(1, 4)},
    **{f"ref_audio_{index}": "" for index in range(1, 4)},
}


def request(*, mode="text_keyframes", prompt="cloud prompt", aspect="adaptive", **media):
    values = dict(EMPTY_MEDIA)
    values.update(media)
    raw = build_cloud_video_request(
        main_mode=mode,
        input_prompt=prompt,
        aspect=aspect,
        duration_seconds=5,
        media_values=values,
    )
    return normalize_cloud_request(raw)


def plan(value):
    return build_fal_plan(
        value,
        execution_mode="dry_run",
        resolution="480P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )


def test_cloud_t2v_adaptive_uses_provider_default_and_fixed_aspect_is_preserved():
    adaptive = plan(request())
    assert adaptive.endpoint == TEXT_ENDPOINT
    assert adaptive.payload["aspect_ratio"] == "16:9"
    assert "source_aspect: adaptive" in adaptive.report
    assert "resolved_aspect: 16:9" in adaptive.report
    assert "reason: cloud_t2v_provider_default" in adaptive.report
    assert "aspect_reason: cloud_t2v_provider_default" in adaptive.report

    fixed = plan(request(aspect="9:16"))
    assert fixed.payload["aspect_ratio"] == "9:16"


def test_cloud_i2v_and_fl2v_follow_first_frame_without_aspect_payload():
    i2v = plan(request(prompt="Animate <Picture 1>", first_frame="frames/first.png"))
    assert i2v.endpoint == IMAGE_ENDPOINT
    assert i2v.payload["prompt"] == "Animate the first frame"
    assert i2v.payload["image_url"] == "fal-upload://input/frames/first.png"
    assert "end_image_url" not in i2v.payload
    assert "aspect_ratio" not in i2v.payload

    fl2v = plan(
        request(
            prompt="Move from <Picture 1> to <Picture 2>",
            first_frame="frames/first.png",
            last_frame="frames/last.png",
        )
    )
    assert fl2v.endpoint == IMAGE_ENDPOINT
    assert fl2v.payload["prompt"] == "Move from the first frame to the last frame"
    assert fl2v.payload["end_image_url"] == "fal-upload://input/frames/last.png"
    assert "aspect_ratio" not in fl2v.payload


def test_cloud_ref2v_adaptive_and_sparse_physical_slots_use_dense_tags():
    value = request(
        mode="all_reference",
        prompt=(
            "Blend <Picture 1> with <Picture 2>; follow <Video 1>; "
            "match <Audio 1> and <Audio 2>."
        ),
        ref_image_2="refs/two.png",
        ref_image_9="refs/nine.png",
        ref_video_3="refs/motion.mp4",
        ref_audio_1="refs/voice.wav",
        ref_audio_3="refs/music.wav",
    )
    result = plan(value)
    assert result.endpoint == REFERENCE_ENDPOINT
    assert result.payload["aspect_ratio"] == "adaptive"
    assert result.payload["prompt"] == (
        "Blend Image 1 with Image 2; follow Video 1; match Audio 1 and Audio 2."
    )
    assert result.payload["reference_image_urls"] == [
        "fal-upload://input/refs/two.png",
        "fal-upload://input/refs/nine.png",
    ]


def test_cloud_embedded_video_audio_never_consumes_audio_tag_namespace():
    value = request(
        mode="all_reference",
        prompt="Use <Video 1> and synchronize <Audio 1>.",
        ref_video_1="refs/audible.mp4",
        ref_audio_2="refs/voice.wav",
    )
    assert adapt_prompt_for_fal(value.routing_prompt, value) == (
        "Use Video 1 and synchronize Audio 1."
    )


def test_cloud_l2v_and_hybrid_audio_keep_explicit_h3_max_errors():
    with pytest.raises(FalValidationError) as error:
        plan(request(last_frame="frames/last.png"))
    assert str(error.value) == (
        "MiniMax H3 Max 当前未实现 Last-Frame-only 路由。\n"
        "请使用本地 H3 或其他明确支持 L2V 的模型。"
    )

    with pytest.raises(FalValidationError, match="Hybrid audio"):
        plan(
            request(
                first_frame="frames/first.png",
                hybrid_audio="audio/guide.wav",
            )
        )


def test_cloud_dry_run_never_constructs_fal_client_or_uploads(monkeypatch):
    from hutx_minimax_h3_testpkg import fal_h3_max

    monkeypatch.setattr(
        fal_h3_max,
        "FalApiClient",
        lambda: (_ for _ in ()).throw(AssertionError("fal client must stay lazy")),
    )
    monkeypatch.setattr(
        fal_h3_max,
        "upload_manifest_media",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no upload in dry run")),
    )
    monkeypatch.setattr(
        fal_h3_max,
        "inspect_manifest_media",
        lambda value: fal_h3_max.MediaInspection(None, None, (), (), ()),
    )
    result = FalH3MaxService().run(
        request(),
        execution_mode="dry_run",
        resolution="480P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )
    assert result.endpoint == TEXT_ENDPOINT
    assert result.local_video_path is None


def test_fal_backend_rejects_unnormalized_mapping_past_the_boundary():
    raw = {"kind": "gh_video_request"}
    with pytest.raises(TypeError, match="NormalizedVideoRequest"):
        build_fal_plan(
            raw,
            execution_mode="dry_run",
            resolution="480P",
            prompt_expansion_mode="balanced",
            seed=-1,
            enable_safety_checker=True,
        )
    with pytest.raises(TypeError, match="NormalizedVideoRequest"):
        FalH3MaxService().run(
            raw,
            execution_mode="dry_run",
            resolution="480P",
            prompt_expansion_mode="balanced",
            seed=-1,
            enable_safety_checker=True,
        )
