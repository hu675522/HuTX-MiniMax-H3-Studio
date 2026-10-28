from __future__ import annotations

import ast
import asyncio
import copy
import importlib
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg.prompt_optimizer import config_schema as schema
from hutx_minimax_h3_testpkg.fal_models import FalValidationError
from hutx_minimax_h3_testpkg.gh_video_request import (
    build_cloud_video_request, migrate_cloud_state_json, normalize_cloud_request,
    validate_cloud_state_json, validate_gh_video_request,
)
from hutx_minimax_h3_testpkg import fal_h3_max

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/optimizer_legacy_frontend_state.json"
SHARED_JS = ROOT / "web/js/prompt_optimizer_shared.js"


def config_response_from_actual_handler(monkeypatch):
    """Execute the real /config handler and normalization, stubbing only I/O.

    Model/dependency scan results use their real source shapes and redacted paths.
    This neither imports a runtime model nor reads any installed model files.
    """
    tree = ast.parse((ROOT / "prompt_optimizer/legacy.py").read_text(encoding="utf-8"))
    namespace = {"__package__": "hutx_minimax_h3_testpkg.prompt_optimizer"}
    for item in tree.body:
        if isinstance(item, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in {"DEFAULT_CONFIG", "PROVIDERS"}
            for target in item.targets
        ):
            exec(compile(ast.Module(body=[item], type_ignores=[]), "legacy.py", "exec"), namespace)
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in {
            "_normalize_config", "_public_config", "get_prompt_optimizer_config",
        }:
            exec(compile(ast.Module(body=[item], type_ignores=[]), "legacy.py", "exec"), namespace)
    fake_legacy = types.ModuleType("hutx_minimax_h3_testpkg.prompt_optimizer.legacy")
    fake_legacy._normalize_config = namespace["_normalize_config"]
    monkeypatch.setitem(sys.modules, fake_legacy.__name__, fake_legacy)
    monkeypatch.setattr(schema, "_environment_api_key", lambda _: "")
    monkeypatch.setattr(schema, "configured_environment_providers", lambda: [])
    preset = namespace["PROVIDERS"]["dashscope"]
    namespace["DEFAULT_CONFIG"].update(provider="dashscope", model=preset[1], api_url=preset[0], protocol=preset[2])
    namespace.update({
        "_RUNNINGHUB_MODELS_CACHE": ["qwen-plus"],
        "_RUNNINGHUB_OVERSEAS_MODELS_CACHE": ["qwen-vl-max"],
        "_scan_visual_models": lambda: [{
            "name": "Example-VL.gguf", "path": "D:/REDACTED/models/llm/Example-VL.gguf",
            "relative_path": "Example-VL.gguf", "format": "gguf", "mmproj_candidates": ["mmproj.gguf"],
        }],
        "_scan_mmproj_models": lambda: [{
            "name": "mmproj.gguf", "path": "D:/REDACTED/models/llm/mmproj.gguf",
            "relative_path": "mmproj.gguf",
        }],
        "_local_missing_dependencies": lambda: ["accelerate"],
        "_gguf_dependency_status": lambda: {
            "available": False, "reason": "offline fixture", "system": "Windows", "machine": "AMD64",
            "python_tag": "cp312", "cuda_tag": "", "release_url": "https://example.invalid/releases",
            "wheel_url": "", "wheel_name": "",
        },
        "web": types.SimpleNamespace(json_response=lambda value: value),
    })
    return asyncio.run(namespace["get_prompt_optimizer_config"](None))


def run_panel(**options):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for actual frontend serializer tests")
    result = subprocess.run([node, str(ROOT / "tests/frontend_optimizer_fixture.mjs")],
                            input=json.dumps(options), capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def run_shared(expression):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for frontend persistence tests")
    source = SHARED_JS.read_text(encoding="utf-8")
    result = subprocess.run([node, "--input-type=module", "-"], input=source + "\n" + expression,
                            capture_output=True, text=True, encoding="utf-8", check=True)
    return result


def build(state):
    return build_cloud_video_request(main_mode="text_keyframes", input_prompt="fallback", aspect="16:9",
                                     duration_seconds=5, media_values={}, gh_cloud_state_json=json.dumps(state))


def test_generated_frontend_schema_is_exactly_the_python_single_source():
    source = SHARED_JS.read_text(encoding="utf-8")
    block = source.split("// BEGIN GENERATED PERSISTENCE SCHEMA (config_schema.py; do not edit by hand)\n")[1]
    block = block.split("\n// END GENERATED PERSISTENCE SCHEMA")[0]
    assert block == schema.render_optimizer_persistence_schema_js()
    assert "_OPTIMIZER_CONFIG_STRINGS" not in (ROOT / "gh_video_request.py").read_text(encoding="utf-8")


def test_fixture_is_produced_by_actual_handler_and_legacy_frontend_serializer(monkeypatch):
    response = config_response_from_actual_handler(monkeypatch)
    # This migration fixture represents an existing, explicitly chosen old model.
    # New provider defaults must not silently rewrite historical workflow choices.
    response['model'] = 'qwen-vl-max'
    capture = run_panel(config=response, legacy=True, loadConfig=True)
    assert capture["state"] == json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert capture["state"]["optimizer"]["config"]["models"][0]["format"] == "gguf"
    assert json.loads(capture["properties"]["gh_cloud_video_state"]) == capture["state"]


def test_real_fixture_load_migrate_validate_save_reload_and_build(monkeypatch):
    legacy = json.loads(FIXTURE.read_text(encoding="utf-8"))
    original = copy.deepcopy(legacy)
    notes = []
    migrated = migrate_cloud_state_json(legacy, notes=notes)
    assert "dropped_legacy_optimizer_ui_field: models" in notes
    assert migrated["optimizer"]["optimizer_state_version"] == 2
    validate_cloud_state_json(migrated)
    assert legacy == original
    # Load the old workflow in the actual panel, fetch runtime config again,
    # then save and reload. Runtime defaults must not re-pollute saved settings.
    response = config_response_from_actual_handler(monkeypatch)
    saved = run_panel(state=legacy, config=response, loadConfig=True)
    reloaded = run_panel(state=saved["state"], config=response, loadConfig=True)
    migrated["optimizer"]["config"]["prompt_profile"] = "auto"
    assert saved["state"] == reloaded["state"] == migrated
    for result in (saved, reloaded):
        assert set(result["state"]["optimizer"]["config"]) <= set(schema.PERSISTED_OPTIMIZER_FIELDS)
        assert "REDACTED/models" not in json.dumps(result)
        request = build(result["state"])
        assert "optimizer" not in request
        assert request["metadata"] == {"source_node": "GHCloudVideoInputGH"}
        assert "model" not in normalize_cloud_request(request).metadata


def test_runtime_models_array_is_removed_but_selected_model_survives():
    runtime = {"provider": "dashscope", "model": "qwen-vl-max", "models": ["qwen-vl-max", "qwen-plus"]}
    assert schema.serialize_public_optimizer_config(runtime) == {"provider": "dashscope", "model": "qwen-vl-max"}
    result = run_shared("console.log(JSON.stringify(serializePublicOptimizerConfig(" + json.dumps(runtime) + ")));" )
    assert json.loads(result.stdout) == schema.serialize_public_optimizer_config(runtime)


@pytest.mark.parametrize("key", ["random_unknown_field", "providers", "modelOptions", "availableModels",
                                   "presets", "providerModels", "lastFetchedModels"])
def test_unconfirmed_fields_are_not_silently_treated_as_migration(key):
    config = {"model": "qwen-plus", key: []}
    with pytest.raises(FalValidationError, match="not a supported persisted"):
        schema.serialize_public_optimizer_config(config)
    result = run_shared("try { serializePublicOptimizerConfig(" + json.dumps(config) + "); } catch(e) { console.log(e.message); }")
    assert "Invalid persisted optimizer setting" in result.stdout


@pytest.mark.parametrize("key", ["api_key", "authorization", "cookie", "secret", "token"])
@pytest.mark.parametrize("nested", [False, True])
def test_secret_is_rejected_even_inside_a_discarded_legacy_cache(key, nested):
    secret = {key: "fixture-secret-not-to-be-logged"}
    config = {"model": "qwen-plus", **({"models": [secret]} if nested else secret)}
    with pytest.raises(FalValidationError, match="secret field") as exc:
        migrate_cloud_state_json({"optimizer": {"config": config}})
    assert "fixture-secret-not-to-be-logged" not in str(exc.value)


def test_frontend_secret_removal_reports_a_security_error_without_disclosing_value():
    result = run_shared("console.log(JSON.stringify(serializePublicOptimizerConfig({model:'qwen-plus',api_key:'fixture-secret'})));")
    assert json.loads(result.stdout) == {"model": "qwen-plus"}
    assert "Security error" in result.stderr
    assert "fixture-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("version", [0, 3, "2", True])
def test_unknown_state_versions_are_rejected(version):
    with pytest.raises(FalValidationError, match="optimizer_state_version"):
        migrate_cloud_state_json({"optimizer": {"optimizer_state_version": version, "config": {}}})


def test_v2_rejects_cache_and_legacy_migration_is_exact_path_only():
    with pytest.raises(FalValidationError, match="not a supported persisted"):
        validate_cloud_state_json({"optimizer": {"optimizer_state_version": 2, "config": {"models": []}}})
    for state in ({"models": []}, {"metadata": {"optimizer": {"config": {"models": []}}}}):
        with pytest.raises(FalValidationError, match="local/backend"):
            validate_cloud_state_json(state)


@pytest.mark.parametrize("container", ["top", "metadata"])
def test_request_models_stays_forbidden(container):
    request = build({})
    (request if container == "top" else request["metadata"])["models"] = []
    with pytest.raises(FalValidationError, match="local/backend"):
        validate_gh_video_request(request)


@pytest.mark.parametrize("variant,prefix", [("H3 Max Turbo", "h3-max-turbo"), ("H3 Max", "h3-max")])
def test_legacy_models_optimizer_disabled_t2v_dry_run(variant, prefix, monkeypatch):
    state = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert state["optimizer"]["config"]["auto_optimize"] is False
    def forbidden(*args, **kwargs):
        raise AssertionError("No fal client/upload/download allowed")
    monkeypatch.setattr(fal_h3_max, "FalApiClient", forbidden)
    monkeypatch.setattr(fal_h3_max, "upload_manifest_media", forbidden)
    monkeypatch.setattr(fal_h3_max, "_download_video", forbidden)
    result = fal_h3_max.FalH3MaxService().run(
        normalize_cloud_request(build(state)), execution_mode="dry_run", model_variant=variant,
        resolution="480P", prompt_expansion_mode="balanced", seed=-1, enable_safety_checker=True,
    )
    assert result.endpoint == f"minimax/{prefix}/text-to-video"
    assert result.local_video_path is None


def test_actual_local_serializer_preserves_user_choices_and_discards_catalogues():
    local_source = (ROOT / "web/js/minimax_h3_integration.js").read_text(encoding="utf-8")
    serializer = local_source.split("    const serializedState = () => {")[1].split("\n    };", 1)[0]
    script = r'''
const state={mode:'text_keyframes'}, prompt={value:'Local prompt'}, promptByMode={};
const media=new Map(), vacantMediaSlots=new Map(), userHeight=620, advanced={open:false};
const optimizerCache=null, optimizerBefore=null, optimizerBeforeByMode={};
const optimizerSettings={mode:'api',provider:'dashscope',model:'qwen-plus',
    provider_models:{dashscope:'qwen-plus',openai:'gpt-4.1-mini'},
    local_model:'chosen.gguf',local_mmproj:'mmproj.gguf',local_device:'cuda',
    models:[{name:'scan result',path:'D:/REDACTED'}],mmproj_models:[],runninghub_models:['qwen-plus']};
const serializedState=()=>{ BODY
};
console.log(serializedState());
'''.replace("BODY", serializer)
    result = json.loads(run_shared(script).stdout)
    config = result["optimizer"]
    assert result["optimizer_state_version"] == 2
    assert config["provider_models"] == {"dashscope": "qwen-plus", "openai": "gpt-4.1-mini"}
    assert config["local_model"] == "chosen.gguf"
    assert not set(config) & set(schema.DERIVED_OPTIMIZER_FIELDS)


def test_optimizer_enabled_with_real_legacy_state_builds_provider_neutral_request(monkeypatch):
    class Output:
        def __init__(self, *values):
            self.values = values
    latest = types.ModuleType("comfy_api.latest")
    latest.io = types.SimpleNamespace(ComfyNode=object, NodeOutput=Output)
    monkeypatch.setitem(sys.modules, "comfy_api", types.ModuleType("comfy_api"))
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    name = "hutx_minimax_h3_testpkg.cloud_video_nodes"
    monkeypatch.delitem(sys.modules, name, raising=False)
    node = importlib.import_module(name).GHCloudVideoInputGH
    state = json.loads(FIXTURE.read_text(encoding="utf-8"))
    output = node.execute(
        main_mode="text_keyframes", prompt=state["prompt"], aspect="16:9", duration_seconds=5,
        gh_cloud_state_json=json.dumps(state), optimizer_enabled=True,
        optimized_prompt="Optimized paper boat scene.", optimizer_report="mock report",
    )
    assert output.values[0]["input_prompt"] == output.values[1] == "Optimized paper boat scene."
    assert "qwen-vl-max" not in json.dumps(output.values[0])
    assert "optimizer_state_version" not in output.values[0]
