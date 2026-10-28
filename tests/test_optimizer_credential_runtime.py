"""Actual Cloud UI events/request bodies, plus the unchanged Python guard.

Every provider, fal, queue, and API response is mocked; no credits are consumed.
"""
from __future__ import annotations

import ast
import copy
import json
import threading

import pytest

from .test_optimizer_persistence import (
    ROOT, config_response_from_actual_handler, run_panel, run_shared,
)
from hutx_minimax_h3_testpkg.prompt_optimizer.secrets import (
    EPHEMERAL_SECRET_STORE, OptimizerCredentialError,
)
from hutx_minimax_h3_testpkg.prompt_optimizer.provider_adapter import resolve_optimizer_api_key

SECRET = "TEST_SECRET_123"
REF = "ghopt_test_xxx"


def panel(monkeypatch, **kwargs):
    config = config_response_from_actual_handler(monkeypatch)
    config["environment_api_key_providers"] = kwargs.pop("environment", [])
    return run_panel(config=config, runtime=True, locale="zh", **kwargs)


def requests(result, route):
    return [item["body"] for item in result["requests"] if item["url"].endswith(route)]


def assert_wire_safe(payload, reference=REF):
    encoded = json.dumps(payload)
    for forbidden in (SECRET, "api_key", "apiKey", "authorization", "bearer", '"key"'):
        assert forbidden not in encoded
    assert payload["config"].get("credential_ref") == reference
    if reference is None:
        assert "credential_ref" not in payload["config"]


def prepare_handler():
    tree = ast.parse((ROOT / "prompt_optimizer/legacy.py").read_text(encoding="utf-8"))
    function = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                    and item.name == "_prepare_prompt_optimization")
    namespace = {"__package__": "hutx_minimax_h3_testpkg.prompt_optimizer", "threading": threading}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "legacy.py", "exec"), namespace)
    return namespace["_prepare_prompt_optimization"]


@pytest.mark.parametrize("automatic", [False, True])
def test_actual_save_reopen_and_optimize_wire_payload(monkeypatch, automatic):
    result = panel(monkeypatch, automatic=automatic)
    assert requests(result, "/secret") == [{"provider": "dashscope", "api_key": SECRET}]
    payload, = requests(result, "/optimize")
    assert_wire_safe(payload)
    runtime = result["runtime"]
    assert runtime["keyDuringExchange"] == runtime["keyAfterSave"] == runtime["reopenedKey"] == ""
    assert runtime["legacyStatusCount"] == 0
    assert runtime["reopenedStatus"] == "会话已配置"
    assert runtime["otherProviderStatus"] == "未配置"
    assert runtime["queueCalls"] == int(automatic)
    assert result["state"]["optimizer"]["optimized_prompt"] == "Optimized paper boat scene."
    assert not result["alerts"]
    for snapshot in (runtime["saved"], runtime["final"]):
        encoded = json.dumps(snapshot)
        for value in (SECRET, REF, "api_key", "apiKey", "credential_ref"):
            assert value not in encoded
    for request in result["requests"]:
        assert request["url"].startswith(("/goohai/minimax-h3/prompt-optimizer/", "/hutx/minimax-h3/prompt-optimizer/credential?"))
        if not request["url"].endswith("/secret"):
            assert SECRET not in json.dumps(request)

    # Replay the actual captured frontend body through the real unchanged guard
    # and normalizer, using the real process-memory store (no provider request).
    reference = EPHEMERAL_SECRET_STORE.put("dashscope", SECRET)
    try:
        replay = copy.deepcopy(payload)
        replay["config"]["credential_ref"] = reference
        config, _ = prepare_handler()(replay)
        assert "api_key" not in config
        assert resolve_optimizer_api_key(config) == SECRET
    finally:
        EPHEMERAL_SECRET_STORE.clear()


def test_reproduces_original_ui_flag_trigger_without_an_inline_secret(monkeypatch):
    config_response_from_actual_handler(monkeypatch)
    old_request = json.loads(run_shared("""
rememberOptimizerCredentials({provider:'dashscope',credential_ref:'ghopt_test_xxx'});
console.log(JSON.stringify({config:withMemoryOptimizerCredentials({provider:'dashscope'})}));
""").stdout)
    assert "api_key" not in old_request["config"]
    assert old_request["config"]["has_api_key"] is True
    with pytest.raises(ValueError, match="Inline API keys are not accepted"):
        prepare_handler()(old_request)


@pytest.mark.parametrize("field", ["api_key", "apiKey", "key", "authorization", "bearer_token"])
@pytest.mark.parametrize("value", ["", SECRET])
def test_request_builder_drops_empty_and_nonempty_secret_aliases(field, value):
    config = {"provider": "dashscope", "mode": "api", field: value}
    result = json.loads(run_shared("""
rememberOptimizerCredentials({provider:'dashscope',credential_ref:'ghopt_test_xxx'});
console.log(JSON.stringify({config:resolveOptimizerCredential(CONFIG)}));
""".replace("CONFIG", json.dumps(config))).stdout)
    assert_wire_safe(result)


@pytest.mark.parametrize("environment", [[], ["dashscope"]])
def test_reload_has_no_session_ref_and_environment_path_has_no_fake_ref(monkeypatch, environment):
    saved = panel(monkeypatch)["runtime"]["saved"]["state"]
    # A fresh Node VM/process models a full page reload: module memory is new.
    result = panel(monkeypatch, state=saved, save=False, environment=environment)
    assert result["runtime"]["initialStatus"] == ("环境变量已配置" if environment else "未配置")
    assert result["runtime"]["reopenedKey"] == ""
    assert not requests(result, "/secret")
    if environment:
        payload, = requests(result, "/optimize")
        assert_wire_safe(payload, reference=None)
        from hutx_minimax_h3_testpkg.prompt_optimizer import config_schema
        monkeypatch.setattr(config_schema, "_environment_api_key", lambda provider: SECRET if provider == "dashscope" else "")
        assert resolve_optimizer_api_key(prepare_handler()(payload)[0]) == SECRET
    else:
        assert not requests(result, "/optimize")
        assert "请配置 API Key 或对应环境变量。" in result["alerts"]


def test_expired_reference_is_reported_and_removed_without_plaintext_fallback(monkeypatch):
    result = panel(monkeypatch, optimizeError="Prompt optimizer session credential is missing or expired; enter the API key again.")
    assert_wire_safe(requests(result, "/optimize")[0])
    assert result["alerts"] == ["LLM API 会话凭证已失效，请重新输入 API Key。"]
    assert result["runtime"]["afterRunStatus"] == "未配置"
    assert SECRET not in json.dumps(result["runtime"]["final"])
    assert len(requests(result, "/secret")) == 1


def test_failed_secret_exchange_clears_password_and_never_optimizes(monkeypatch):
    result = panel(monkeypatch, secretError=True)
    assert result["runtime"]["keyDuringExchange"] == result["runtime"]["keyAfterSave"] == ""
    assert result["runtime"]["reopenedStatus"] == "未配置"
    assert not requests(result, "/optimize")
    assert SECRET not in json.dumps(result["state"])


def test_provider_binding_survives_status_switch_and_rejects_backend_reuse(monkeypatch):
    result = json.loads(run_shared("""
rememberOptimizerCredentials({provider:'dashscope',credential_ref:'ghopt_test_xxx'});
const status=optimizerCredentialStatus({provider:'custom',credential_ref:'ghopt_test_xxx'}, en=>en);
console.log(JSON.stringify({status,config:resolveOptimizerCredential({provider:'custom'})}));
""").stdout)
    assert result["status"] == "Not configured"
    assert "credential_ref" not in result["config"]
    config_response_from_actual_handler(monkeypatch)
    ref = EPHEMERAL_SECRET_STORE.put("dashscope", SECRET)
    try:
        with pytest.raises(OptimizerCredentialError, match="missing or expired"):
            resolve_optimizer_api_key(prepare_handler()({"config": {"provider": "custom", "credential_ref": ref}})[0])
    finally:
        EPHEMERAL_SECRET_STORE.clear()


def test_local_and_cloud_manual_auto_share_request_resolver():
    cloud = (ROOT / "web/js/prompt_optimizer_shared.js").read_text(encoding="utf-8")
    local = (ROOT / "web/js/minimax_h3_integration.js").read_text(encoding="utf-8")
    assert "config: resolveOptimizerCredential(config)" in cloud
    assert "config: resolveOptimizerCredential(optimizerSettings)" in local
    assert "run({ automatic: true })" in cloud
    assert "runPromptOptimization({ automatic: true })" in local


def test_cloud_output_two_and_three_use_actual_manual_result(monkeypatch):
    import importlib
    import sys
    import types

    result = panel(monkeypatch)
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
    optimizer = result["state"]["optimizer"]
    output = node.execute(main_mode="text_keyframes", prompt=result["state"]["prompt"],
                          aspect="16:9", duration_seconds=5,
                          gh_cloud_state_json=json.dumps(result["state"]), optimizer_enabled=False,
                          optimized_prompt=optimizer["optimized_prompt"],
                          optimizer_report=optimizer["optimizer_report"])
    assert output.values[1] == "Optimized paper boat scene."
    assert output.values[2] == optimizer["optimizer_report"]
    assert SECRET not in json.dumps(output.values)
