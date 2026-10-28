from __future__ import annotations

import json

from hutx_minimax_h3_testpkg.fal_models import build_source_manifest


def _media_values(**overrides):
    values = {
        "first_frame": "",
        "last_frame": "",
        "hybrid_audio": "",
        **{f"ref_image_{index}": "" for index in range(1, 10)},
        **{f"ref_video_{index}": "" for index in range(1, 4)},
        **{f"ref_audio_{index}": "" for index in range(1, 4)},
    }
    values.update(overrides)
    return values


def test_reference_manifest_is_versioned_active_only_and_relative(tmp_path):
    state = json.dumps(
        {
            "promptOptimizer": {"apiKey": "must-not-leak"},
            "media": [
                ["ref_video_2", {"kind": "video", "name": "clips/v.mp4", "muted": True}],
                [
                    "ref_audio_3",
                    {"kind": "audio", "name": "audio/a.wav", "trimStart": 2.5, "trimEnd": 8.0},
                ],
            ],
        }
    )
    manifest = build_source_manifest(
        input_prompt="raw <Picture 3>",
        conditioned_prompt="ready <Picture 3>",
        main_mode="all_reference",
        aspect="adaptive",
        width=1024,
        height=576,
        requested_duration_seconds=5,
        local_frame_count=124,
        media_values=_media_values(
            first_frame="inactive.png",
            ref_image_1="images/one.png",
            ref_image_3="images/three.png",
            ref_video_2="clips/v.mp4",
            ref_audio_3="audio/a.wav",
        ),
        gh_state_json=state,
        input_directory=tmp_path,
        reference_video_audio_slots=set(),
    )

    assert manifest["schema_version"] == 1
    assert manifest["resolved_task"] == "ref2va"
    assert manifest["first_frame"] is None
    assert manifest["last_frame"] is None
    assert manifest["hybrid_audio"] is None
    assert [item["slot"] for item in manifest["reference_images"]] == ["ref_image_1", "ref_image_3"]
    assert manifest["reference_videos"] == [
        {"slot": "ref_video_2", "name": "clips/v.mp4", "muted": True, "has_audio": False}
    ]
    assert manifest["reference_audios"] == [
        {
            "slot": "ref_audio_3",
            "name": "audio/a.wav",
            "trim_start": 2.5,
            "trim_end": 8.0,
        }
    ]
    assert manifest["target"]["local_duration_seconds"] == 124 / 24
    serialized = json.dumps(manifest)
    assert "must-not-leak" not in serialized
    assert str(tmp_path) not in serialized


def test_keyframe_manifest_ignores_stale_references_and_resolves_fl2va(tmp_path):
    manifest = build_source_manifest(
        input_prompt="raw",
        conditioned_prompt="conditioned",
        main_mode="text_keyframes",
        aspect="16:9",
        width=1024,
        height=576,
        requested_duration_seconds=6,
        local_frame_count=141,
        media_values=_media_values(
            first_frame="first.png",
            last_frame="last.png",
            ref_image_1="inactive.png",
        ),
        input_directory=tmp_path,
    )
    assert manifest["resolved_task"] == "fl2va"
    assert manifest["first_frame"]["name"] == "first.png"
    assert manifest["last_frame"]["name"] == "last.png"
    assert manifest["reference_images"] == []
    assert manifest["reference_videos"] == []
    assert manifest["reference_audios"] == []


def test_open_ended_hybrid_trim_is_preserved(tmp_path):
    state = json.dumps(
        {"media": [["hybrid_audio", {"kind": "audio", "trimStart": 1.25, "trimEnd": None}]]}
    )
    manifest = build_source_manifest(
        input_prompt="raw",
        conditioned_prompt="conditioned",
        main_mode="text_keyframes",
        aspect="16:9",
        width=1024,
        height=576,
        requested_duration_seconds=5,
        local_frame_count=124,
        media_values=_media_values(first_frame="first.png", hybrid_audio="hybrid.wav"),
        gh_state_json=state,
        input_directory=tmp_path,
    )
    assert manifest["resolved_task"] == "i2va"
    assert manifest["hybrid_audio"] == {
        "slot": "hybrid_audio",
        "name": "hybrid.wav",
        "trim_start": 1.25,
        "trim_end": None,
    }
