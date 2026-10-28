from __future__ import annotations

import asyncio
import json
import os
import shutil
from types import SimpleNamespace

import pytest

from hutx_minimax_h3_testpkg.prompt_optimizer import credentials as c, config_schema, provider_adapter
from hutx_minimax_h3_testpkg.prompt_optimizer.secrets import EPHEMERAL_SECRET_STORE, OptimizerCredentialError
from .test_optimizer_persistence import config_response_from_actual_handler, run_panel
from .test_optimizer_runtime_serialization import backend

KEY = "TEST_OPTIMIZER_PERSISTED_SECRET_123"


@pytest.fixture
def manager():
    EPHEMERAL_SECRET_STORE.clear()
    yield c.PROMPT_OPTIMIZER_CREDENTIALS
    EPHEMERAL_SECRET_STORE.clear()


@pytest.mark.skipif(os.name != "nt", reason="Windows Current User DPAPI")
@pytest.mark.parametrize("provider", list(config_schema.PROVIDER_ENV_KEYS))
def test_actual_dpapi_save_restart_provider_bound(manager, provider):
    manager.save(provider, KEY)
    document = manager.path(provider).read_text()
    assert KEY not in document and KEY[:10] not in document and KEY[-8:] not in document
    assert set(json.loads(document)) == {"version", "provider", "encrypted_blob", "metadata"}
    restarted = c.PromptOptimizerCredentialManager(manager.directory)
    assert restarted.resolve(provider) == KEY
    assert restarted.status(provider)["active_source"] == "persisted"
    other = "openai" if provider != "openai" else "dashscope"
    assert restarted.resolve(other) == ""


@pytest.mark.parametrize("env,session,persisted", [(False,False,False),(True,False,False),(False,True,False),(False,False,True),(False,True,True),(True,True,True)])
def test_resolution_priority_and_status(manager, monkeypatch, env, session, persisted):
    if persisted: manager.save("dashscope", KEY)
    reference = EPHEMERAL_SECRET_STORE.put("dashscope", "TEST_SESSION_KEY") if session else None
    if env: monkeypatch.setenv("DASHSCOPE_API_KEY", "TEST_ENV_KEY")
    expected = "environment" if env else "session" if session else "persisted" if persisted else "none"
    status = manager.status("dashscope", reference)
    assert status == {"provider":"dashscope", "configured":expected != "none", "active_source":expected,
                      "environment_configured":env,"session_configured":session,"persisted_configured":persisted,"persistence_supported":True}
    assert manager.resolve("dashscope", reference) == ("TEST_ENV_KEY" if env else "TEST_SESSION_KEY" if session else KEY if persisted else "")


def test_provider_ciphertext_cannot_be_relabelled(manager):
    manager.save("dashscope", KEY)
    data = json.loads(manager.path("dashscope").read_text())
    data["provider"] = "openai"
    manager.path("openai").write_text(json.dumps(data))
    with pytest.raises(c.PersistedCredentialUnavailable): manager.resolve("openai")
    assert manager.resolve("dashscope") == KEY


def test_delete_only_selected_provider_preserves_session_environment(manager, monkeypatch):
    for provider in ("dashscope", "openai"): manager.save(provider, KEY)
    ref = EPHEMERAL_SECRET_STORE.put("dashscope", "TEST_SESSION_KEY")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "TEST_ENV_KEY")
    manager.delete("dashscope")
    assert manager.resolve("dashscope", ref) == "TEST_ENV_KEY"
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    assert manager.resolve("dashscope", ref) == "TEST_SESSION_KEY"
    assert manager.resolve("openai") == KEY


def test_invalid_and_expired_reference_still_fail_closed(manager):
    manager.save("openai", KEY)
    ref = EPHEMERAL_SECRET_STORE.put("dashscope", "SESSION")
    with pytest.raises(OptimizerCredentialError, match="missing or expired"): manager.resolve("openai", ref)
    EPHEMERAL_SECRET_STORE.clear()
    with pytest.raises(OptimizerCredentialError, match="missing or expired"): manager.resolve("openai", ref)


def test_env_mapping_cannot_reuse_generic_custom_key(manager, monkeypatch):
    monkeypatch.setenv("GH_PROMPT_OPTIMIZER_API_KEY", "CUSTOM_ONLY")
    assert manager.resolve("custom") == manager.resolve("openai-compatible") == "CUSTOM_ONLY"
    assert manager.resolve("dashscope") == manager.resolve("openai") == ""
    with pytest.raises(OptimizerCredentialError): manager.resolve("../../FAL_KEY")


def request(method, provider="dashscope", body=None, reference=None):
    async def data(): return dict(body or {})
    return SimpleNamespace(method=method,query={"provider":provider},headers={"X-HuTX-Optimizer-Reference":reference} if reference else {},json=data)


def test_routes_return_only_status_and_no_refs_or_ciphertext(manager):
    ref = EPHEMERAL_SECRET_STORE.put("dashscope", "TEST_SESSION")
    async def run():
        for req in (request("POST", body={"provider":"dashscope","api_key":KEY},reference=ref),request("GET",reference=ref),request("DELETE",reference=ref)):
            response = await c.credential_route(req)
            assert response.status == 200
            status = json.loads(response.text)
            assert set(status) == {"provider","configured","active_source","environment_configured","session_configured","persisted_configured","persistence_supported"}
            assert KEY not in response.text and ref not in response.text
            assert status["session_configured"]
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["corrupted", "wrong_user"])
def test_corrupted_or_wrong_user_keeps_file_and_safe_status(manager, monkeypatch, failure):
    manager.save("dashscope", KEY)
    if failure == "corrupted": manager.path("dashscope").write_text("broken")
    else:
        def fail(_): raise RuntimeError(KEY)
        monkeypatch.setattr(manager.cipher, "decrypt", fail)
    before = manager.path("dashscope").read_bytes()
    response = asyncio.run(c.credential_route(request("GET")))
    assert response.status == 409 and KEY not in response.text
    assert manager.path("dashscope").read_bytes() == before
    with pytest.raises(c.PersistedCredentialUnavailable, match="本机凭证不可用"): manager.resolve("dashscope")


def test_unsupported_os_never_writes_plaintext(manager):
    manager.cipher = SimpleNamespace(supported=False)
    with pytest.raises(OptimizerCredentialError, match="不支持"): manager.save("dashscope", KEY)
    assert not manager.path("dashscope").exists()
    ref = EPHEMERAL_SECRET_STORE.put("dashscope", "SESSION")
    assert manager.resolve("dashscope", ref) == "SESSION"


def test_provider_adapter_resolves_persisted_without_config_secret(manager, backend, monkeypatch, caplog):
    manager.save("dashscope", KEY)
    async def provider(config, payload, *, api_key, cancel_event):
        assert api_key == KEY
        assert KEY not in json.dumps(config) + json.dumps(payload)
        return "optimized"
    monkeypatch.setattr(backend, "_request_async", provider)
    assert asyncio.run(provider_adapter.request_optimized_prompt({"mode":"api","provider":"dashscope"}, {})) == "optimized"
    async def fail(*args, **kwargs): raise RuntimeError("HTTP 401 echoed " + KEY + " prefix=" + KEY[:8] + " suffix=" + KEY[-8:] + " credential length=" + str(len(KEY)))
    monkeypatch.setattr(backend, "_request_async", fail)
    with pytest.raises(RuntimeError) as error: asyncio.run(provider_adapter.request_optimized_prompt({"mode":"api","provider":"dashscope"}, {}))
    assert KEY not in str(error.value) + caplog.text
    assert KEY[:8] not in str(error.value) + caplog.text
    assert KEY[-8:] not in str(error.value) + caplog.text


def ui(monkeypatch, **options):
    config = config_response_from_actual_handler(monkeypatch)
    config["provider"] = "dashscope"
    return run_panel(config=config,locale="zh",secureCredentials=True,**options)


@pytest.mark.parametrize("automatic", [False, True])
def test_persist_save_manual_auto_workflow_and_report_secret_free(monkeypatch, automatic):
    result = ui(monkeypatch,runtime=True,persistSave=True,automatic=automatic)
    assert result["runtime"]["keyAfterSave"] == result["runtime"]["reopenedKey"] == ""
    posts = [r for r in result["requests"] if r["method"]=="POST"]
    assert any("/credential?" in r["url"] and r["body"]["api_key"] == "TEST_SECRET_123" for r in posts)
    optimize = next(r for r in posts if r["url"].endswith("/optimize"))
    assert "api_key" not in json.dumps(optimize) and "credential_ref" not in json.dumps(optimize)
    for field in ("state","properties","widgets_values"):
        assert "TEST_SECRET_123" not in json.dumps(result[field])
    assert result["state"]["optimizer"]["optimized_prompt"]


def test_provider_switch_buttons_feedback_and_clear(monkeypatch):
    result = ui(monkeypatch,credentialActions=[{"type":"session"},{"type":"persisted"},{"type":"input","value":"TEST_SECRET_123"},{"type":"persisted"},{"type":"provider","value":"openai"},{"type":"provider","value":"dashscope"},{"type":"delete"}])
    states = result["credentialSnapshots"]
    assert states[0]["kind"] == states[1]["kind"] == "error"
    assert states[3]["kind"] == "success" and states[3]["key"] == ""
    assert "Windows DPAPI 已保存" in states[3]["status"]
    assert "未保存" in states[4]["status"] and "Windows DPAPI 已保存" in states[5]["status"]
    assert "未保存" in states[6]["status"]
    assert result["runtime"]["inputDuringCredentialSave"] == ""


@pytest.mark.parametrize("environment", [[],["dashscope"]])
def test_session_then_persist_warning_and_delete_source(environment, monkeypatch):
    result = ui(monkeypatch,environment=environment,credentialActions=[{"type":"input","value":"TEST_SESSION"},{"type":"session"},{"type":"input","value":"TEST_PERSIST"},{"type":"persisted"},{"type":"delete"}])
    states = result["credentialSnapshots"]
    assert states[3]["kind"] == "warning"
    assert "环境变量生效" in states[3]["feedback"] if environment else "本次会话凭证生效" in states[3]["feedback"]
    assert "当前生效：● 环境变量" in states[-1]["status"] if environment else "当前生效：● 本次会话" in states[-1]["status"]


def test_reload_persisted_without_session_or_fake_ref(monkeypatch):
    result = ui(monkeypatch,runtime=True,save=False,initialCredentials={"dashscope":True})
    optimize = next(r for r in result["requests"] if r["url"].endswith("/optimize"))
    assert "credential_ref" not in json.dumps(optimize) and "api_key" not in json.dumps(optimize)
