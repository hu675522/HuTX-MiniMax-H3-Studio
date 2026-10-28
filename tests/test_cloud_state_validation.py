from __future__ import annotations

import copy
import importlib
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg import fal_h3_max
from hutx_minimax_h3_testpkg.fal_models import FalValidationError
from hutx_minimax_h3_testpkg.gh_video_request import (
    build_cloud_video_request,
    normalize_cloud_request,
    validate_cloud_state_json,
    validate_gh_video_request,
)


ROOT = Path(__file__).resolve().parents[1]
MODELS = ["qwen-vl-max", "gpt-4.1-mini", "qwen-plus"]


def ui_state(model="qwen-vl-max", *, image=False):
    return {
        "schema_version": 1, "mode": "text_keyframes", "aspect": "adaptive",
        "duration_seconds": 5, "prompt": "Animate <Picture 1>." if image else "A paper boat sails.",
        "media": [["first_frame", {"name": "frames/first.png", "kind": "image"}]] if image else [],
        "optimizer": {
            "config": {
                "mode": "api", "provider": "dashscope", "model": model,
                "api_url": "https://example.invalid/v1", "protocol": "openai",
                "max_tokens": 4096, "output_language": "English", "read_media": True,
                "auto_optimize": False,
            },
            "original_prompt": "A paper boat sails.",
            "optimized_prompt": "A cinematic paper boat sails.",
            "optimizer_report": "mock optimizer report",
        },
    }


def build(state=None):
    return build_cloud_video_request(
        main_mode="text_keyframes", input_prompt="Fallback", aspect="16:9",
        duration_seconds=5, media_values={},
        gh_cloud_state_json=json.dumps(state) if state is not None else "",
    )


@pytest.fixture
def cloud_node(monkeypatch):
    class Output:
        def __init__(self, *values):
            self.values = values

    latest = types.ModuleType("comfy_api.latest")
    latest.io = types.SimpleNamespace(ComfyNode=object, NodeOutput=Output)
    monkeypatch.setitem(sys.modules, "comfy_api", types.ModuleType("comfy_api"))
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    name = "hutx_minimax_h3_testpkg.cloud_video_nodes"
    monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module(name).GHCloudVideoInputGH


def execute(cloud_node, state, *, enabled=False):
    return cloud_node.execute(
        main_mode="text_keyframes", prompt=state["prompt"], aspect="16:9",
        duration_seconds=5, gh_cloud_state_json=json.dumps(state),
        optimizer_enabled=enabled,
        optimized_prompt=state["optimizer"]["optimized_prompt"],
        optimizer_report=state["optimizer"]["optimizer_report"],
    )


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("enabled", [False, True])
def test_saved_t2v_optimizer_model_queues_with_optimizer_enabled_or_disabled(cloud_node, model, enabled):
    state = ui_state(model)
    original = copy.deepcopy(state)
    output = execute(cloud_node, state, enabled=enabled)
    request = output.values[0]
    expected_prompt = state["optimizer"]["optimized_prompt"] if enabled else state["prompt"]
    assert request["input_prompt"] == expected_prompt
    assert request["resolved_task"] == "t2v"
    assert request["metadata"] == {"source_node": "GHCloudVideoInputGH"}
    assert "optimizer" not in request and model not in json.dumps(request)
    normalized = normalize_cloud_request(request)
    assert normalized.input_prompt == expected_prompt
    assert dict(normalized.metadata) == request["metadata"]
    assert state == original  # Validation must not clear old optimizer settings.


@pytest.mark.parametrize("model", MODELS)
def test_saved_i2v_optimizer_model_queues_without_reading_media(cloud_node, model):
    state = ui_state(model, image=True)
    request = execute(cloud_node, state).values[0]
    assert request["resolved_task"] == "i2v"
    assert request["first_frame"] == {"slot": "first_frame", "name": "frames/first.png"}
    assert request["input_prompt"] == "Animate <Picture 1>."


def test_all_current_persisted_config_fields_and_requested_aliases_are_supported():
    state = ui_state()
    state["optimizer"]["config"].update({
        "base_url": "https://example.invalid/v1", "temperature": 0.2, "timeout": 60,
        "read_visual_media": False, "provider_models": {"dashscope": "qwen-plus"},
        "local_model": "", "local_mmproj": "", "local_device": "cuda",
        "environment_api_key_providers": ["dashscope"],
        "runninghub_models": ["qwen-plus"], "runninghub_overseas_models": [],
    })
    original = copy.deepcopy(state)
    validate_cloud_state_json(state)
    request = build(state)
    assert state == original
    assert request["metadata"] == {"source_node": "GHCloudVideoInputGH"}
    assert "provider_models" not in json.dumps(request)


@pytest.mark.parametrize("value", [{"weights": []}, [], object(), b"binary", lambda: None, None, 1, True])
def test_optimizer_model_must_be_a_string(value):
    state = ui_state(value)
    with pytest.raises(FalValidationError, match=r"optimizer\.config\.model (must be a string LLM model name|contains a non-JSON)"):
        validate_cloud_state_json(state)


@pytest.mark.parametrize("value", [{}, [], 123, None])
def test_optimizer_base_url_must_be_a_string(value):
    state = ui_state()
    state["optimizer"]["config"]["base_url"] = value
    with pytest.raises(FalValidationError, match=r"config\.base_url must be a string"):
        validate_cloud_state_json(state)


@pytest.mark.parametrize("key", [
    "model", "MODEL", "model_variant", "fal_model", "endpoint", "payload",
    "fal_endpoint", "fal_payload", "CLIP", "VAE", "LATENT", "CONDITIONING",
])
@pytest.mark.parametrize("container", ["top", "metadata"])
def test_request_backend_fields_stay_forbidden_at_every_level(key, container):
    request = build(ui_state())
    target = request if container == "top" else request["metadata"]
    target[key] = "H3 Max Turbo"
    with pytest.raises(FalValidationError, match="local/backend"):
        validate_gh_video_request(request)
    with pytest.raises(FalValidationError, match="local/backend"):
        normalize_cloud_request(request)


@pytest.mark.parametrize("extra", [
    {"model": "qwen-plus"},
    {"optimizer.config": {"model": "qwen-plus"}},
    {"metadata": {"optimizer": {"config": {"model": "qwen-plus"}}}},
    {"optimizer": {"config": {"MODEL": "qwen-plus"}}},
    {"optimizer": {"config": [{"model": "qwen-plus"}]}},
    {"metadata": {"model_variant": "H3 Max Turbo"}},
    {"optimizer": {"config": {"model_variant": "H3 Max Turbo"}}},
    {"optimizer": {"config": {"model": "qwen-plus", "CLIP": {}}}},
    {"metadata": {"payload": {}}},
])
def test_ui_model_exception_is_only_for_the_exact_structural_path(extra):
    state = ui_state()
    state.update(extra)
    with pytest.raises(FalValidationError, match="local/backend|not a supported persisted|must be an object"):
        validate_cloud_state_json(state)


@pytest.mark.parametrize("key", ["api_key", "Authorization", "Cookie", "Secret", "token", "credential_ref"])
def test_ui_optimizer_secrets_are_rejected_without_echoing_values(key):
    state = ui_state()
    state["optimizer"]["config"][key] = "sensitive-test-value"
    with pytest.raises(FalValidationError, match="secret field") as exc:
        build(state)
    assert "sensitive-test-value" not in str(exc.value)


@pytest.mark.parametrize("value", [object(), b"binary", lambda: None, float("nan"), float("inf")])
def test_ui_non_json_runtime_values_are_rejected(value):
    state = ui_state()
    state["extra"] = value
    with pytest.raises(FalValidationError, match="non-JSON|non-finite"):
        validate_cloud_state_json(state)


@pytest.mark.parametrize("variant,prefix", [("H3 Max", "h3-max"), ("H3 Max Turbo", "h3-max-turbo")])
def test_t2v_dry_run_with_saved_optimizer_model_for_both_fal_variants(cloud_node, monkeypatch, variant, prefix):
    def forbidden(*args, **kwargs):
        raise AssertionError("Dry run must not call fal, upload, or download")

    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(fal_h3_max, "FalApiClient", forbidden)
    monkeypatch.setattr(fal_h3_max, "upload_manifest_media", forbidden)
    monkeypatch.setattr(fal_h3_max, "_download_video", forbidden)
    request = execute(cloud_node, ui_state(), enabled=True).values[0]
    result = fal_h3_max.FalH3MaxService().run(
        normalize_cloud_request(request), execution_mode="dry_run", model_variant=variant,
        resolution="480P", prompt_expansion_mode="balanced", seed=-1, enable_safety_checker=True,
    )
    assert result.endpoint == f"minimax/{prefix}/text-to-video"
    assert result.payload["prompt"] == "A cinematic paper boat sails."
    assert result.payload["aspect_ratio"] == "16:9"
    assert "qwen-vl-max" not in result.report
    assert result.local_video_path is None


def test_real_frontend_sanitizer_keeps_llm_model_but_not_secret_in_workflow_queue_history():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for workflow serialization testing")
    source = (ROOT / "web/js/prompt_optimizer_shared.js").read_text(encoding="utf-8")
    script = source + "\n" + r'''
const config = sanitizeOptimizerConfig({provider:'dashscope',model:'qwen-vl-max',
    api_key:'sensitive-test-value',credential_ref:'ghopt_test-reference',max_tokens:4096});
const state = {mode:'text_keyframes',prompt:'A paper boat sails.',media:[],optimizer:{config}};
const stateJson = JSON.stringify(state);
const workflow = {nodes:[{properties:{gh_cloud_state_json:stateJson},widgets_values:[stateJson]}]};
const queue = {prompt:{'1':{inputs:{gh_cloud_state_json:stateJson}}}};
const history = {prompt:queue.prompt,outputs:{}};
console.log(JSON.stringify({state,workflow,queue,history}));
'''
    result = subprocess.run([node, "--input-type=module", "-"], input=script,
                            check=True, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert "sensitive-test-value" not in result.stdout
    assert "ghopt_test-reference" not in result.stdout
    assert "api_key" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["state"]["optimizer"]["config"]["model"] == "qwen-vl-max"
    validate_cloud_state_json(payload["state"])
    assert build(payload["state"])["resolved_task"] == "t2v"
    for container in (payload["workflow"], payload["queue"], payload["history"]):
        assert "qwen-vl-max" in json.dumps(container)
