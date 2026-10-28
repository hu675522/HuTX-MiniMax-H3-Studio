from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_name_based_socket_preservation_regressions():
    result = subprocess.run(
        [shutil.which("node"), str(ROOT / "tests/dual_engine_input_links_fixture.mjs")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    report = json.loads(result.stdout)
    assert report["reload_driver_link"] is not None
    assert report["engine_switch_links"] == 6
    assert report["protected"] == [
        "driver_audio", "reference_audio_1", "reference_audio_2", "reference_audio_3",
        "continuation_latent", "continuation_frames", "continuation_audio",
    ]


def test_engine_mode_controls_only_associated_second_pass_and_face_switches():
    result = subprocess.run(
        [shutil.which("node"), str(ROOT / "tests/dual_engine_switches_fixture.mjs")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert json.loads(result.stdout) == {"switches": 2, "transitions": 3, "unchangedLinks": 5}


def test_old_node_is_not_enrolled_in_dual_restore_lifecycle():
    source = (ROOT / "web/js/gh_local_video_input.js").read_text(encoding="utf-8")
    assert "if(node?.type!=='GHLocalVideoInputDualEngineGH')return" in source
    assert "restoreInputConnectionsByName" in source
    assert "captureConfiguredInputConnectionsByName" in source


def test_minimal_workflow_serializes_driver_audio_link_by_name():
    workflow = json.loads((ROOT / "docs/workflows/dual-engine-driver-audio-link-regression.json").read_text(encoding="utf-8"))
    speech = next(node for node in workflow["nodes"] if node["type"] == "GHSpeechInputGH")
    dual = next(node for node in workflow["nodes"] if node["type"] == "GHLocalVideoInputDualEngineGH")
    driver_slot = next(index for index, item in enumerate(dual["inputs"]) if item["name"] == "driver_audio")
    link = workflow["links"][0]
    assert link == [1, speech["id"], 0, dual["id"], driver_slot, "AUDIO"]
    assert dual["inputs"][driver_slot]["link"] == link[0]
