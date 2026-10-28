from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from hutx_minimax_h3_testpkg.fal_models import FalValidationError
from hutx_minimax_h3_testpkg.gh_video_request import (
    GH_PROMPT_TAG_SCHEME,
    LEGACY_PROMPT_TAG_SCHEME,
    NormalizedVideoRequest,
    build_cloud_video_request,
    normalize_cloud_request,
    normalize_video_request,
)


MEDIA_VALUES = {
    "first_frame": "",
    "last_frame": "",
    "hybrid_audio": "",
    **{f"ref_image_{index}": "" for index in range(1, 10)},
    **{f"ref_video_{index}": "" for index in range(1, 4)},
    **{f"ref_audio_{index}": "" for index in range(1, 4)},
}


def cloud_request(*, mode="text_keyframes", prompt="cloud prompt", aspect="adaptive", **media):
    values = dict(MEDIA_VALUES)
    values.update(media)
    return build_cloud_video_request(
        main_mode=mode,
        input_prompt=prompt,
        aspect=aspect,
        duration_seconds=5,
        media_values=values,
    )


def legacy_manifest(task="i2va"):
    first = {"slot": "first_frame", "name": "frames/first.png"} if task in {"i2va", "fl2va"} else None
    last = {"slot": "last_frame", "name": "frames/last.png"} if task in {"l2va", "fl2va"} else None
    return {
        "schema_version": 1,
        "input_prompt": "raw prompt",
        "conditioned_prompt": "conditioned prompt",
        "main_mode": "text_keyframes",
        "resolved_task": task,
        "aspect": "adaptive",
        "target": {
            "width": 1280,
            "height": 736,
            "requested_duration_seconds": 5,
            "local_frame_count": 124,
            "local_duration_seconds": 124 / 24,
        },
        "first_frame": first,
        "last_frame": last,
        "reference_images": [],
        "reference_videos": [],
        "reference_audios": [],
        "hybrid_audio": None,
    }


@pytest.mark.parametrize(
    ("media", "expected"),
    [
        ({}, "t2v"),
        ({"first_frame": "first.png"}, "i2v"),
        ({"last_frame": "last.png"}, "l2v"),
        ({"first_frame": "first.png", "last_frame": "last.png"}, "fl2v"),
    ],
)
def test_cloud_keyframe_tasks_are_derived(media, expected):
    request = cloud_request(**media)
    assert request["resolved_task"] == expected
    assert normalize_cloud_request(request).resolved_task == expected


def test_cloud_reference_task_and_metadata_are_normalized_immutably():
    request = cloud_request(
        mode="all_reference",
        ref_image_7="refs/look.png",
        ref_video_3="refs/motion.mp4",
        ref_audio_2="refs/voice.wav",
    )
    request["reference_videos"][0]["muted"] = True
    request["reference_audios"][0].update({"trim_start": 1.25, "trim_end": 4.5})
    request["metadata"]["nested"] = {"provider_neutral": True}

    normalized = normalize_cloud_request(request)
    assert isinstance(normalized, NormalizedVideoRequest)
    assert normalized.resolved_task == "ref2v"
    assert normalized.prompt_tag_scheme == GH_PROMPT_TAG_SCHEME
    assert normalized.reference_images[0].slot == "ref_image_7"
    assert normalized.reference_videos[0].muted is True
    assert normalized.reference_audios[0].trim_start == pytest.approx(1.25)
    with pytest.raises(FrozenInstanceError):
        normalized.resolved_task = "t2v"
    with pytest.raises(TypeError):
        normalized.metadata["changed"] = True
    with pytest.raises(TypeError):
        normalized.metadata["nested"]["changed"] = True


def test_all_reference_without_media_falls_back_with_a_visible_note():
    normalized = normalize_cloud_request(cloud_request(mode="all_reference"))
    assert normalized.resolved_task == "t2v"
    assert normalized.validation_notes == (
        "all_reference_without_references_fallback_to_t2v",
    )


def test_cloud_normalizer_rederives_task_and_rejects_frontend_mismatch():
    request = cloud_request(first_frame="first.png")
    request["resolved_task"] = "t2v"
    with pytest.raises(FalValidationError, match="does not match active media"):
        normalize_cloud_request(request)


def test_inactive_mode_media_are_filtered_and_state_removal_is_authoritative():
    state = {
        "schema_version": 1,
        "mode": "text_keyframes",
        "prompt": "restored",
        "aspect": "9:16",
        "duration_seconds": 6,
        "media": [["first_frame", {"name": "state-first.png", "kind": "image"}]],
    }
    values = dict(MEDIA_VALUES)
    values.update(
        {
            "first_frame": "stale-widget-first.png",
            "last_frame": "stale-widget-last.png",
            "ref_image_1": "inactive-reference.png",
        }
    )
    request = build_cloud_video_request(
        main_mode="all_reference",
        input_prompt="stale prompt",
        aspect="adaptive",
        duration_seconds=5,
        media_values=values,
        gh_cloud_state_json=json.dumps(state),
    )
    assert request["resolved_task"] == "i2v"
    assert request["first_frame"]["name"] == "state-first.png"
    assert request["last_frame"] is None
    assert request["reference_images"] == []
    assert request["input_prompt"] == "restored"


@pytest.mark.parametrize(
    "name",
    [
        "../outside.png",
        "..\\outside.png",
        "C:\\private\\image.png",
        "D:/private/image.png",
        "/home/user/image.png",
        "https://example.com/image.png",
        "image.png [input]",
    ],
)
def test_cloud_media_rejects_non_input_relative_names(name):
    with pytest.raises(FalValidationError):
        cloud_request(first_frame=name)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conditioning", "forbidden"),
        ("latent", {}),
        ("model", "forbidden"),
        ("vae", "forbidden"),
        ("clip", "forbidden"),
        ("tensor", "forbidden"),
        ("width", 1280),
        ("height", 720),
        ("local_frame_count", 124),
        ("endpoint", "minimax/h3-max/text-to-video"),
        ("payload", {}),
        ("api_key", "secret"),
        ("FAL_KEY", "secret"),
    ],
)
def test_cloud_request_rejects_local_backend_and_secret_fields(field, value):
    request = cloud_request()
    request["metadata"][field] = value
    with pytest.raises(FalValidationError):
        normalize_cloud_request(request)


def test_cloud_request_rejects_non_json_model_like_objects():
    request = cloud_request()
    request["metadata"]["opaque"] = object()
    with pytest.raises(FalValidationError, match="non-JSON"):
        normalize_cloud_request(request)


def test_legacy_normalizer_preserves_prompts_canvas_and_media_metadata():
    value = legacy_manifest("i2va")
    value["reference_videos"] = [
        {
            "slot": "ref_video_2",
            "name": "refs/motion.mp4",
            "muted": False,
            "has_audio": True,
        }
    ]
    normalized = normalize_video_request({"source_manifest": value})
    assert normalized.source_kind == "legacy_minimax"
    assert normalized.input_prompt == "raw prompt"
    assert normalized.routing_prompt == "conditioned prompt"
    assert normalized.prompt_tag_scheme == LEGACY_PROMPT_TAG_SCHEME
    assert normalized.resolved_task == "i2v"
    assert normalized.legacy_canvas == (1280, 736)
    assert normalized.reference_videos[0].has_audio is True


def test_unknown_input_contract_is_rejected():
    with pytest.raises(FalValidationError, match="neither"):
        normalize_video_request({"kind": "unrelated_custom_type"})
