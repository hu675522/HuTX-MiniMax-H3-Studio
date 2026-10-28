from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from .test_optimizer_runtime_serialization import backend, Request, exchange, response_data
from hutx_minimax_h3_testpkg.prompt_optimizer import engine
from hutx_minimax_h3_testpkg.prompt_optimizer.template_manager import (
    OptimizerTagValidationError, cloud_media_label_counts, protect_cloud_input_prompt,
    restore_cloud_prompt,
)
from hutx_minimax_h3_testpkg.prompt_tags import MEDIA_TAG_RE
from hutx_minimax_h3_testpkg.gh_video_request import build_cloud_video_request, normalize_cloud_request
from hutx_minimax_h3_testpkg.fal_media import InspectedMedia, MediaInspection, upload_manifest_media
from hutx_minimax_h3_testpkg.fal_router import build_fal_plan

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("<Picture 1>", "<Picture 2>", "<Video 1>", "<Audio 1>")
MEDIA = [{"kind": kind, "label": label} for kind, label in zip(("image", "image", "video", "audio"), LABELS)]
SOURCE = (
    "Use <Picture 1> as the main character identity reference.\n"
    "Use <Picture 2> as the clothing and appearance styling reference.\n"
    "Follow the movement and shot rhythm of <Video 1>.\n"
    "Match the pacing and emotional tone of <Audio 1>.\n"
    "Create a smooth, cinematic 5-second video with coherent motion and natural continuity."
)


def run_route(monkeypatch, backend, *, source=SOURCE, task="Ref2VA", media=MEDIA, transform=lambda text, protection: text):
    protection = protect_cloud_input_prompt(source, task, media)
    trace = {}
    original_restore = engine.restore_cloud_prompt
    def observe_restore(candidate, protected):
        trace["before_restore"] = {tag: candidate.count(token) for tag, token in protected.placeholders_by_tag.items()}
        restored = original_restore(candidate, protected)
        trace["after_restore"] = cloud_media_label_counts(restored, protected.active_tags)
        return restored
    async def mock_provider(config, data, *, api_key, cancel_event):
        assert api_key == "TEST_SECRET_123"
        assert data["prompt"] == protection.protected_prompt
        trace["protected_prompt"] = data["prompt"]
        trace["provider_media_count"] = len(data["media"])
        response = transform(data["prompt"], protection)
        trace["llm_raw_response"] = response
        trace["llm_counts"] = {tag: response.count(token) for tag, token in protection.placeholders_by_tag.items()}
        return response
    monkeypatch.setattr(engine, "restore_cloud_prompt", observe_restore)
    monkeypatch.setattr(backend, "_request_async", mock_provider)
    async def run():
        ref = await exchange(backend)
        request = {"prompt": source, "task": task, "media": copy.deepcopy(media),
                   "tag_contract": "gh_media_v1", "duration": 5,
                   "config": {"provider": "dashscope", "model": "qwen-vl-max", "credential_ref": ref}}
        before = copy.deepcopy(request)
        response = await backend.optimize_prompt(Request(request))
        assert request == before
        assert ref not in response.text and "TEST_SECRET_123" not in response.text
        return response.status, response_data(response)
    status, result = asyncio.run(run())
    return status, result, trace


def plan_and_upload(optimized, task, slots):
    raw = build_cloud_video_request(main_mode="all_reference" if task == "Ref2VA" else "text_keyframes",
                                    input_prompt=optimized, aspect="16:9", duration_seconds=5, media_values=slots)
    normalized = normalize_cloud_request(raw)
    inspect = lambda item: InspectedMedia(item, Path(item.name)) if item else None
    inspection = MediaInspection(inspect(normalized.first_frame), inspect(normalized.last_frame),
                                 tuple(map(inspect, normalized.reference_images)),
                                 tuple(map(inspect, normalized.reference_videos)),
                                 tuple(map(inspect, normalized.reference_audios)))
    uploads = []
    def uploader(path):
        uploads.append(str(path))
        return "https://mock.invalid/" + str(path).replace("\\", "/")
    class MockCache:
        def upload(self, path, *, transform, uploader, timing, media_kind, slot):
            return uploader(path)
    urls = upload_manifest_media(inspection, uploader=uploader, cache=MockCache())
    plan = build_fal_plan(normalized, execution_mode="dry_run", resolution="480P", prompt_expansion_mode="balanced",
                          seed=-1, enable_safety_checker=True, media_urls=urls)
    return normalized, plan, uploads


def test_exact_reported_ref2v_case_has_duplicates_before_restore(monkeypatch, backend):
    evidence = json.loads((ROOT / "docs/media-label-multiplicity-reproduction-v0.2.3.3.json").read_text(encoding="utf-8"))
    status, result, trace = run_route(monkeypatch, backend, transform=lambda *_: evidence["mock_llm_raw_response"])
    assert status == 200
    expected = dict(zip(LABELS, (2, 1, 2, 1)))
    assert trace["protected_prompt"] == evidence["raw_protected_prompt"]
    assert trace["llm_counts"] == trace["before_restore"] == trace["after_restore"] == expected
    report = json.loads(result["report"])
    assert report["media_label_counts_before"] == dict.fromkeys(LABELS, 1)
    assert report["media_label_counts_after"] == expected
    assert report["media_label_multiplicity_changed"] is True
    for forbidden in ("__GH", "credential_ref", "TEST_SECRET_123", "api_key"):
        assert forbidden not in result["report"]
    assert "<Picture 1>" in result["prompt"] and "Image 1" not in result["prompt"]


@pytest.mark.parametrize("task,media,slots", [
    ("I2VA", MEDIA[:1], {"first_frame": "first.png"}),
    ("FL2VA", MEDIA[:2], {"first_frame": "first.png", "last_frame": "last.png"}),
    ("Ref2VA", MEDIA[:1], {"ref_image_7": "identity.png"}),
    ("Ref2VA", MEDIA, {"ref_image_3": "identity.png", "ref_image_8": "style.png", "ref_video_2": "motion.mp4", "ref_audio_3": "tone.wav"}),
])
@pytest.mark.parametrize("repeat", [2, 5])
def test_duplicates_preserved_but_uploads_and_urls_are_slot_based(monkeypatch, backend, task, media, slots, repeat):
    source = " ".join(f"Use {item['label']} as reference." for item in media)
    status, result, trace = run_route(monkeypatch, backend, source=source, task=task, media=media,
                                     transform=lambda text, _: "\n".join([text] * repeat))
    assert status == 200, result
    for item in media:
        assert result["prompt"].count(item["label"]) == repeat
    assert trace["provider_media_count"] == len(slots)
    normalized, plan, uploads = plan_and_upload(result["prompt"], task, slots)
    assert len(uploads) == len(slots)
    assert len(set(uploads)) == len(slots)
    if task == "Ref2VA":
        for kind, name in (("Picture", "image"), ("Video", "video"), ("Audio", "audio")):
            count = sum(item["kind"] == name for item in media)
            assert len(getattr(normalized, "reference_" + name + "s")) == count
            assert len(plan.payload.get("reference_" + name + "_urls", [])) == count
        for item in media:
            target = item["label"].strip("<>").replace("Picture", "Image")
            assert plan.prompt.count(target) == repeat
    else:
        assert plan.prompt.count("the first frame") == repeat
        assert plan.payload["image_url"] == "https://mock.invalid/first.png"
        assert "reference_image_urls" not in plan.payload
        if task == "FL2VA":
            assert plan.prompt.count("the last frame") == repeat
            assert plan.payload["end_image_url"] == "https://mock.invalid/last.png"
        else:
            assert "end_image_url" not in plan.payload


@pytest.mark.parametrize("extra", ["<Picture 3>", "Image 3", "<Video 2>", "<Audio 2>",
                                  "__GH_MEDIA_V1_PICTURE_3_FORGED__"])
def test_unknown_or_inactive_label_rejected(monkeypatch, backend, extra):
    status, result, _ = run_route(monkeypatch, backend, transform=lambda text, _: text + " " + extra)
    assert status == 400
    assert "error" in result


@pytest.mark.parametrize("missing", LABELS)
def test_required_label_cannot_disappear(monkeypatch, backend, missing):
    status, result, _ = run_route(monkeypatch, backend, transform=lambda text, p: text.replace(p.placeholders_by_tag[missing], "the reference"))
    assert status == 400
    assert f"damaged protected media label {missing}: expected at least 1, found 0" in result["error"]


@pytest.mark.parametrize("damage", [lambda p: p[:-3], lambda p: p.lower(), lambda p: p + p,
                                   lambda p: "prefix" + p, lambda p: p + "_suffix",
                                   lambda p: p.replace("_V1_", "_V2_"), lambda p: p[:8]])
def test_damaged_placeholder_rejected_even_if_valid_copy_remains(damage):
    protection = protect_cloud_input_prompt(SOURCE, "Ref2VA", MEDIA)
    token = protection.placeholders_by_tag["<Picture 1>"]
    with pytest.raises(OptimizerTagValidationError, match="altered or invented"):
        restore_cloud_prompt(protection.protected_prompt + " " + damage(token), protection)


def test_multiple_original_mentions_may_reduce_to_one_and_no_change_is_observable(monkeypatch, backend):
    status, result, _ = run_route(monkeypatch, backend, source=SOURCE + "\n" + SOURCE,
                                 transform=lambda text, _: text[:len(text) // 2])
    assert status == 200
    report = json.loads(result["report"])
    assert report["media_label_counts_before"] == dict.fromkeys(LABELS, 2)
    assert report["media_label_counts_after"] == dict.fromkeys(LABELS, 1)


def test_unchanged_counts_report_false(monkeypatch, backend):
    status, result, _ = run_route(monkeypatch, backend)
    assert status == 200
    report = json.loads(result["report"])
    assert report["media_label_counts_before"] == report["media_label_counts_after"]
    assert report["media_label_multiplicity_changed"] is False


def test_existing_requirement_to_reference_all_active_media_is_preserved():
    with pytest.raises(OptimizerTagValidationError, match="missing: <Picture 2>"):
        protect_cloud_input_prompt("Use <Picture 1>.", "Ref2VA", MEDIA[:2])


def test_cloud_system_instructions_allow_repetition_without_provider_label_conversion(backend):
    protection = protect_cloud_input_prompt(SOURCE, "Ref2VA", MEDIA)
    instructions = backend._system_prompt("Ref2VA", 5, list(protection.placeholders_by_tag.values()),
                                         context={"tag_contract": "gh_media_v1"}, user_prompt=protection.protected_prompt)
    assert "Repeating an existing supplied" in instructions
    assert "at least once" in instructions
    assert "exact occurrence count" not in instructions
    assert "Never emit numbered Picture, Image, Video, or Audio labels directly" in instructions


@pytest.mark.parametrize("contract", ["gh_media_v1", "local_h3_v1"])
@pytest.mark.parametrize("task", ["I2VA", "FL2VA", "Ref2VA"])
@pytest.mark.parametrize("user_prompt", ["Move the subject.", "Replace the person in the video with the person in the picture."])
def test_protected_system_prompt_never_teaches_raw_media_labels(backend, contract, task, user_prompt):
    instructions = backend._system_prompt(
        task, 5, ["__GH_MEDIA_V1_PICTURE_1_TEST__"], "English",
        {"tag_contract": contract, "resolved_prompt_profile": "structured"},
        user_prompt,
    )
    assert MEDIA_TAG_RE.search(instructions) is None
    assert "__GH_MEDIA_V1_PICTURE_1_TEST__" in instructions


def test_chinese_prose_can_touch_complete_placeholders_and_counts_are_canonical():
    protection = protect_cloud_input_prompt("参考 <Picture 1>。", "I2VA", MEDIA[:1])
    token = protection.placeholders_by_tag["<Picture 1>"]
    result = restore_cloud_prompt(f"以{token}为身份参考，保持{token}的发型。", protection)
    assert result.count("<Picture 1>") == 2
    assert cloud_media_label_counts(result, ["<picture 1>"]) == {"<Picture 1>": 2}
