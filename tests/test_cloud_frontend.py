from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED = PROJECT_ROOT / "web" / "js" / "gh_video_input_shared.js"
CLOUD_UI = PROJECT_ROOT / "web" / "js" / "gh_cloud_video_input.js"


def _run_shared_helper(expression: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    source = SHARED.read_text(encoding="utf-8").replace("export ", "")
    script = f"{source}\nconsole.log(JSON.stringify({expression}));"
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_frontend_uses_cloud_specific_state_and_does_not_wrap_queue_or_optimizer():
    source = CLOUD_UI.read_text(encoding="utf-8")
    assert 'const STATE_PROPERTY = "gh_cloud_video_state"' in source
    assert 'const STATE_WIDGET = "gh_cloud_state_json"' in source
    assert "gh_h3_state" not in source
    assert "queuePrompt" not in source
    assert "DashScope" not in source
    assert "RunningHub" not in source
    assert "api_key" not in source.lower()
    assert "decodeAudioData" not in source
    assert "AudioContext" not in source
    assert 'createMediaCard' in source
    assert 'preview.preload = "metadata"' in (CLOUD_UI.parent / 'video_input_components.js').read_text(encoding='utf-8')


def test_frontend_dense_tags_ignore_sparse_physical_slot_suffixes():
    result = _run_shared_helper("(() => {\n"
        "  const media = new Map([\n"
        "    ['ref_image_2', {name: 'two.png'}],\n"
        "    ['ref_image_9', {name: 'nine.png'}],\n"
        "    ['ref_video_3', {name: 'motion.mp4'}],\n"
        "    ['ref_audio_2', {name: 'voice.wav'}],\n"
        "  ]);\n"
        "  return [\n"
        "    promptTagForSlot('all_reference', 'ref_image_2', media),\n"
        "    promptTagForSlot('all_reference', 'ref_image_9', media),\n"
        "    promptTagForSlot('all_reference', 'ref_video_3', media),\n"
        "    promptTagForSlot('all_reference', 'ref_audio_2', media),\n"
        "  ];\n"
        "})()")
    assert result == ["<Picture 1>", "<Picture 2>", "<Video 1>", "<Audio 1>"]


def test_frontend_state_parse_restore_round_trip_shape():
    state = {
        "schema_version": 1,
        "mode": "all_reference",
        "prompt": "Use <Picture 1>",
        "aspect": "adaptive",
        "duration_seconds": 5,
        "media": [["ref_image_7", {"name": "refs/look.png", "kind": "image"}]],
    }
    encoded = json.dumps(state)
    expression = f"parseCloudState({json.dumps(encoded)})"
    assert _run_shared_helper(expression) == state


def test_frontend_mode_derivation_ignores_inactive_media_groups():
    result = _run_shared_helper("(() => {\n"
        "  const media = new Map([\n"
        "    ['first_frame', {name: 'first.png'}],\n"
        "    ['ref_image_1', {name: 'inactive.png'}],\n"
        "  ]);\n"
        "  return [deriveCloudTask('text_keyframes', media), deriveCloudTask('all_reference', media)];\n"
        "})()")
    assert result == ["i2v", "ref2v"]
