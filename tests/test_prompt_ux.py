from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from .test_optimizer_persistence import run_panel
from .test_optimizer_runtime_serialization import backend, Request, exchange, response_data
from hutx_minimax_h3_testpkg.prompt_optimizer.template_manager import protect_cloud_input_prompt, OptimizerTagValidationError

ROOT = Path(__file__).resolve().parents[1]


def state(mode="text_keyframes", **media):
    return {"mode": mode, "prompt": "", "aspect": "16:9", "duration_seconds": 5,
            "media": [[slot, {"name": name}] for slot, name in media.items()]}


def panel(saved, actions):
    return run_panel(state=saved, uxActions=actions, locale="zh")


@pytest.mark.parametrize("saved,expected", [
    (state(first_frame="first.png", ref_image_3="inactive.png"), [("@首帧", "first.png")]),
    (state(first_frame="first.png", last_frame="last.png", hybrid_audio="voice.wav"),
     [("@首帧", "first.png"), ("@尾帧", "last.png"), ("@音频1", "voice.wav")]),
    (state("all_reference", first_frame="inactive.png", ref_image_2="01.png", ref_image_8="06 (1).png",
           ref_video_3="M01_SlowDollyIn_raw.mp4", ref_audio_2="夏日慢时光.MP3"),
     [("@图片1", "01.png"), ("@图片2", "06 (1).png"), ("@视频1", "M01_SlowDollyIn_raw.mp4"), ("@音频1", "夏日慢时光.MP3")]),
])
def test_at_opens_only_active_media_in_canonical_order(saved, expected):
    result = panel(saved, [{"type": "type", "text": "Use @"}])
    menu = result["ux"][0]
    assert menu["hidden"] is False
    assert [(row["name"], row["filename"]) for row in menu["rows"]] == expected
    assert all(row["filename"] in row["title"] for row in menu["rows"])


@pytest.mark.parametrize("saved,query,tag", [
    (state(first_frame="first.png"), "首帧", "<Picture 1>"),
    (state(first_frame="first.png", last_frame="last.png"), "尾帧", "<Picture 2>"),
    (state(first_frame="first.png", hybrid_audio="song.mp3"), "音频", "<Audio 1>"),
    (state("all_reference", ref_image_2="same.png", ref_image_8="same.png"), "图片2", "<Picture 2>"),
    (state("all_reference", ref_video_3="movie with spaces.mp4"), "with spaces", "<Video 1>"),
    (state("all_reference", ref_audio_2="夏日慢时光.MP3"), "夏日", "<Audio 1>"),
])
def test_search_and_enter_insert_only_canonical_tags_into_workflow(saved, query, tag):
    result = panel(saved, [{"type": "type", "text": "Use @" + query}, {"type": "key", "key": "Enter"}])
    assert result["state"]["prompt"] == "Use " + tag
    assert result["ux"][-1]["hidden"] is True
    assert "@" not in json.dumps(result["properties"])
    assert "@" not in json.dumps(result["widgets_values"])
    assert not result["requests"]


def test_keyboard_wrap_escape_and_mouse_insertion_at_caret():
    result = panel(state(first_frame="first.png", last_frame="last.png"), [
        {"type": "type", "text": "Before @ after", "caret": 8},
        {"type": "key", "key": "ArrowUp"},
        {"type": "key", "key": "ArrowDown"},
        {"type": "key", "key": "Escape"},
        {"type": "type", "text": "Before @尾 after", "caret": 9},
        {"type": "click", "index": 0},
    ])
    assert result["ux"][1]["rows"][1]["selected"] == "true"
    assert result["ux"][2]["rows"][0]["selected"] == "true"
    assert result["ux"][3]["hidden"] is True
    assert result["state"]["prompt"] == "Before <Picture 2> after"
    assert result["ux"][-1]["caret"] == len("Before <Picture 2>")


def test_delete_recomputes_live_entries_without_rewriting_existing_prompt():
    result = panel(state("all_reference", ref_image_2="same.png", ref_image_8="same.png"), [
        {"type": "type", "text": "Use <Picture 2>. @图"},
        {"type": "delete", "tag": "<Picture 2>"},
        {"type": "key", "key": "Enter"},
    ])
    assert [row["name"] for row in result["ux"][1]["rows"]] == ["@图片1"]
    assert result["state"]["prompt"] == "Use <Picture 2>. <Picture 1>"
    with pytest.raises(OptimizerTagValidationError, match="inactive"):
        protect_cloud_input_prompt(result["state"]["prompt"], "Ref2VA", [{"kind": "image", "label": "<Picture 1>"}])


def test_filename_replacement_and_mode_switch_refresh_current_slots():
    result = panel(state(first_frame="old.png", ref_image_8="ref.png"), [
        {"type": "type", "text": "@"},
        {"type": "mode", "index": 1},
        {"type": "restore", "state": {**state("all_reference", ref_image_8="新名字 (1).png"), "prompt": "@"}},
        {"type": "key", "key": "Enter"},
    ])
    assert result["ux"][1]["rows"][0]["name"] == "@图片1"
    assert result["ux"][2]["rows"][0]["filename"] == "新名字 (1).png"
    assert result["state"]["prompt"] == "<Picture 1>"


def test_empty_menu_and_non_whitespace_query_do_not_insert_fake_media():
    result = panel(state(), [{"type": "type", "text": "@"}, {"type": "key", "key": "Enter"},
                            {"type": "type", "text": "user@example.com"}])
    assert result["ux"][0]["rows"] == []
    assert result["ux"][1]["text"] == "@"
    assert result["ux"][2]["hidden"] is False
    assert result["ux"][2]["rows"] == []


@pytest.mark.parametrize("prefix", ["", "abc", "中文", "<Picture 1>", "<Video 1>", "<Audio 1>", "，", "。"])
def test_new_at_has_no_preceding_character_boundary(prefix):
    result = panel(state("all_reference", ref_image_2="pic.png"), [
        {"type": "type", "text": prefix}, {"type": "insert", "text": "@"},
        {"type": "insert", "text": "图"}, {"type": "key", "key": "Enter"},
    ])
    assert result["ux"][1]["hidden"] is False
    assert [row["name"] for row in result["ux"][2]["rows"]] == ["@图片1"]
    assert result["state"]["prompt"] == prefix + "<Picture 1>"
    assert result["ux"][-1]["caret"] == len(prefix + "<Picture 1>")


def test_consecutive_mentions_insert_adjacent_canonical_tags_and_keep_caret():
    result = panel(state("all_reference", ref_image_2="pic.png", ref_video_3="vid.mp4"), [
        {"type": "type", "text": "@"}, {"type": "key", "key": "Enter"},
        {"type": "insert", "text": "@"}, {"type": "insert", "text": "视"},
        {"type": "key", "key": "Enter"},
    ])
    assert result["ux"][2]["hidden"] is False
    assert result["ux"][2]["text"] == "<Picture 1>@"
    assert result["state"]["prompt"] == "<Picture 1><Video 1>"
    assert result["ux"][-1]["caret"] == len("<Picture 1><Video 1>")
    assert "@" not in json.dumps(result["properties"])
    assert "@" not in json.dumps(result["widgets_values"])
    assert result["requests"] == []


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
@pytest.mark.parametrize("delay_config", [False, True])
def test_timing_lifecycle_and_duplicate_click_guard(automatic, outcome, delay_config):
    result = subprocess.run([shutil.which("node"), str(ROOT / "tests/frontend_prompt_timing_fixture.mjs")],
                            input=json.dumps({"automatic": automatic, "outcome": outcome, "delayConfig": delay_config}),
                            encoding="utf-8", capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert data["initial"]["hidden"] is True
    assert data["immediate"]["text"] == ("● 自动优化中 0.0s" if automatic else "● 优化中 0.0s")
    assert data["immediate"]["disabled"] is True
    for phase in ("immediate", "ticking", "finished", "stopped"):
        assert data[phase]["visibleBadges"] == 1
        assert data[phase]["legacyStatuses"] == 0
    assert data["duplicate"] is False
    assert data["ticking"]["text"] == ("● 自动优化中 3.7s" if automatic else "● 优化中 3.7s")
    assert data["finished"]["state"] == ("cancelled" if outcome == "cancel" else outcome)
    assert data["finished"]["disabled"] is False
    assert "4.26s" in data["finished"]["text"]
    assert data["finished"] == data["stopped"]
    assert data["intervals"] == 0
    assert len([call for call in data["calls"] if call["url"].endswith("/optimize")]) == 1
    assert not any(call["url"].endswith("/secret") for call in data["calls"])
    assert data["report"]["optimizer_frontend_elapsed_seconds"] == pytest.approx(4.26)
    if outcome == "success": assert data["report"]["optimizer_elapsed_seconds"] == 2.5
    if outcome == "cancel": assert not data["alerts"]


def test_backend_route_timing_report_uses_monotonic_clock_and_excludes_secret_save(monkeypatch, backend):
    tick = {"time": 10.0}
    monkeypatch.setattr(backend, "time", types.SimpleNamespace(perf_counter=lambda: tick["time"]))
    async def provider(config, data, **runtime):
        tick["time"] += 2.75
        return "A woman walks in the rain."
    monkeypatch.setattr(backend, "_request_async", provider)
    async def run():
        ref = await exchange(backend)
        tick["time"] += 90  # Time spent configuring credentials is outside /optimize.
        response = await backend.optimize_prompt(Request({"prompt": "A woman walks in the rain.", "task": "T2VA",
            "media": [], "tag_contract": "gh_media_v1", "config": {"provider": "dashscope", "credential_ref": ref}}))
        assert response.status == 200
        report = response_data(response)["report"]
        assert json.loads(report)["optimizer_elapsed_seconds"] == 2.75
        assert "credential_ref" not in report and "TEST_SECRET_123" not in report
    asyncio.run(run())
