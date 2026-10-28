from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg.fal_models import (
    FalValidationError,
    estimate_h3_max_cost,
)
from hutx_minimax_h3_testpkg.fal_router import build_fal_plan
from hutx_minimax_h3_testpkg.gh_video_request import normalize_video_request


FIXTURE = Path(__file__).parent / "fixtures" / "v01_legacy_fal_workflow.json"


def _plan(manifest):
    request = normalize_video_request({"source_manifest": manifest})
    return build_fal_plan(
        request,
        execution_mode="dry_run",
        resolution="480P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )


def test_v01_workflow_link_load_and_json_round_trip_stays_on_integration_socket():
    workflow = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fal_node = next(node for node in workflow["nodes"] if node["type"] == "FalH3MaxVideoGH")
    integration_node = next(
        node for node in workflow["nodes"] if node["type"] == "MiniMaxH3IntegrationGH"
    )
    link = next(link for link in workflow["links"] if link[0] == 100)
    assert fal_node["inputs"][0] == {"name": "integration", "type": "MiniMax", "link": 100}
    assert integration_node["outputs"][0]["links"] == [100]
    assert link == [100, 10, 0, 20, 0, "MiniMax"]

    reloaded = json.loads(json.dumps(workflow, ensure_ascii=False))
    assert reloaded["links"] == workflow["links"]
    assert reloaded["nodes"] == workflow["nodes"]


@pytest.mark.parametrize("case_name", ["t2v", "i2v", "fl2v", "ref2v"])
def test_v01_legacy_dry_run_payload_semantic_snapshots(case_name):
    workflow = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = workflow["extra"]["compatibility_cases"][case_name]
    result = _plan(case["manifest"])
    assert result.endpoint == case["expected_endpoint"]
    assert result.payload == case["expected_payload"]
    estimate = estimate_h3_max_cost(
        resolved_task=result.resolved_task,
        endpoint=result.endpoint,
        output_duration_seconds=result.payload["duration"],
        resolution=result.payload["resolution"],
        as_of=date(2026, 9, 4),
    )
    assert estimate.output_video_cost == pytest.approx(case["expected_output_cost"])


def test_v01_legacy_l2v_error_snapshot():
    workflow = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = workflow["extra"]["compatibility_cases"]["l2v"]
    with pytest.raises(FalValidationError) as error:
        _plan(case["manifest"])
    assert str(error.value) == case["expected_error"]
