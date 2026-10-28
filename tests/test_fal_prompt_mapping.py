from __future__ import annotations

import pytest

from hutx_minimax_h3_testpkg.fal_models import FalValidationError
from hutx_minimax_h3_testpkg.fal_router import adapt_prompt_for_fal
from hutx_minimax_h3_testpkg.gh_video_request import (
    build_cloud_video_request,
    normalize_cloud_request,
    normalize_video_request,
)


def reference_manifest(*, videos=None, audios=None):
    return {
        "schema_version": 1,
        "input_prompt": "raw",
        "conditioned_prompt": "conditioned",
        "main_mode": "all_reference",
        "resolved_task": "ref2va",
        "aspect": "adaptive",
        "target": {
            "width": 1024,
            "height": 576,
            "requested_duration_seconds": 5.0,
            "local_frame_count": 124,
        },
        "first_frame": None,
        "last_frame": None,
        "reference_images": [
            {"slot": "ref_image_1", "name": "one.png"},
            {"slot": "ref_image_3", "name": "three.png"},
        ],
        "reference_videos": videos or [
            {"slot": "ref_video_2", "name": "two.mp4", "muted": True, "has_audio": False}
        ],
        "reference_audios": audios or [
            {"slot": "ref_audio_1", "name": "one.wav"},
            {"slot": "ref_audio_3", "name": "three.wav"},
        ],
        "hybrid_audio": None,
    }


def legacy_request(value):
    return normalize_video_request({"source_manifest": value})


def test_sparse_slots_are_repacked_to_actual_fal_array_order():
    prompt = "<Picture 1>, picture 3, <Video 2>, <Audio 1>, and audio 2"
    adapted = adapt_prompt_for_fal(prompt, legacy_request(reference_manifest()))
    assert adapted == "Image 1, Image 2, Video 1, Audio 1, and Audio 2"


def test_muted_video_does_not_consume_local_audio_ordinal():
    value = reference_manifest(
        videos=[{"slot": "ref_video_2", "name": "two.mp4", "muted": True, "has_audio": True}],
        audios=[{"slot": "ref_audio_3", "name": "three.wav"}],
    )
    assert adapt_prompt_for_fal("Audio 1", legacy_request(value)) == "Audio 1"


def test_standalone_audio_after_video_soundtrack_is_repacked():
    value = reference_manifest(
        videos=[{"slot": "ref_video_2", "name": "two.mp4", "muted": False, "has_audio": True}],
        audios=[{"slot": "ref_audio_3", "name": "three.wav"}],
    )
    assert adapt_prompt_for_fal("Audio 2", legacy_request(value)) == "Audio 1"
    with pytest.raises(FalValidationError, match="reference-video soundtrack"):
        adapt_prompt_for_fal("Audio 1", legacy_request(value))


def test_tag_for_inactive_sparse_slot_is_an_error():
    with pytest.raises(FalValidationError, match="no active fal"):
        adapt_prompt_for_fal("Picture 2", legacy_request(reference_manifest()))


def test_i2v_picture_tag_becomes_natural_first_frame_language():
    value = {
        "schema_version": 1,
        "input_prompt": "raw",
        "conditioned_prompt": "conditioned",
        "main_mode": "text_keyframes",
        "resolved_task": "i2va",
        "aspect": "adaptive",
        "target": {"width": 1024, "height": 576, "requested_duration_seconds": 5.0, "local_frame_count": 124},
        "first_frame": {"slot": "first_frame", "name": "opening.png"},
        "last_frame": None,
        "reference_images": [],
        "reference_videos": [],
        "reference_audios": [],
        "hybrid_audio": None,
    }
    prompt = "The woman from <Picture 1> turns toward camera; rain and dialogue continue."
    request = legacy_request(value)
    assert adapt_prompt_for_fal(prompt, request) == (
        "The woman from the first frame turns toward camera; rain and dialogue continue."
    )
    with pytest.raises(FalValidationError, match="no active fal keyframe"):
        adapt_prompt_for_fal("Use Picture 2", request)


def test_fl2v_picture_tags_become_natural_first_and_last_frame_language():
    value = {
        "schema_version": 1,
        "input_prompt": "raw",
        "conditioned_prompt": "conditioned",
        "main_mode": "text_keyframes",
        "resolved_task": "fl2va",
        "aspect": "adaptive",
        "target": {"width": 1024, "height": 576, "requested_duration_seconds": 5.0, "local_frame_count": 124},
        "first_frame": {"slot": "first_frame", "name": "opening.png"},
        "last_frame": {"slot": "last_frame", "name": "ending.png"},
        "reference_images": [],
        "reference_videos": [],
        "reference_audios": [],
        "hybrid_audio": None,
    }
    prompt = "Move from picture 1 through a crane shot into <Picture 2>, keeping the music."
    assert adapt_prompt_for_fal(prompt, legacy_request(value)) == (
        "Move from the first frame through a crane shot into the last frame, keeping the music."
    )


def test_cloud_sparse_slots_are_numbered_by_active_array_position():
    media = {
        "ref_image_2": "two.png",
        "ref_image_8": "eight.png",
        "ref_video_3": "motion.mp4",
        "ref_audio_2": "voice.wav",
    }
    request = build_cloud_video_request(
        main_mode="all_reference",
        input_prompt="<Picture 1>, <Picture 2>, <Video 1>, <Audio 1>",
        aspect="adaptive",
        duration_seconds=5,
        media_values=media,
    )
    normalized = normalize_cloud_request(request)
    assert adapt_prompt_for_fal(normalized.routing_prompt, normalized) == (
        "Image 1, Image 2, Video 1, Audio 1"
    )


def test_cloud_video_soundtrack_does_not_shift_explicit_audio_numbering():
    request = build_cloud_video_request(
        main_mode="all_reference",
        input_prompt="<Video 1> and <Audio 1>",
        aspect="adaptive",
        duration_seconds=5,
        media_values={"ref_video_1": "audible.mp4", "ref_audio_3": "voice.wav"},
    )
    normalized = normalize_cloud_request(request)
    assert adapt_prompt_for_fal(normalized.routing_prompt, normalized) == "Video 1 and Audio 1"
