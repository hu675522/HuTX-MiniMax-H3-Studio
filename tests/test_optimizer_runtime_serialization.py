from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import pickle
import sys
import threading
import types
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg.prompt_optimizer import config_schema, engine
from hutx_minimax_h3_testpkg.prompt_optimizer.secrets import EPHEMERAL_SECRET_STORE
from hutx_minimax_h3_testpkg.prompt_optimizer.template_manager import (
    protect_cloud_input_prompt, protect_cloud_payload_bindings,
)

ROOT = Path(__file__).resolve().parents[1]
SECRET = "TEST_SECRET_123"


@pytest.fixture
def backend(monkeypatch):
    """Load the entire real route module; stub Comfy host and all external I/O."""
    import hutx_minimax_h3_testpkg.prompt_optimizer as package
    folder_paths = types.ModuleType("folder_paths")
    server = types.ModuleType("server")
    server.PromptServer = types.SimpleNamespace(instance=None)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setitem(sys.modules, "server", server)
    name = package.__name__ + ".legacy"
    spec = importlib.util.spec_from_file_location(name, ROOT / "prompt_optimizer/legacy.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(package.__dict__, "legacy", module)
    spec.loader.exec_module(module)
    def forbidden(*args, **kwargs):
        raise AssertionError("External network/model operation forbidden in mock tests")
    monkeypatch.setattr(module.aiohttp, "ClientSession", forbidden)
    monkeypatch.setattr(module, "_local_generate", forbidden)
    monkeypatch.setattr(config_schema, "_environment_api_key", lambda _: "")
    EPHEMERAL_SECRET_STORE.clear()
    yield module
    EPHEMERAL_SECRET_STORE.clear()


class Request:
    def __init__(self, payload):
        self.payload = payload
        self.query = payload

    async def json(self):
        return copy.deepcopy(self.payload)


def response_data(response):
    return json.loads(response.text)


async def exchange(backend):
    response = await backend.store_prompt_optimizer_secret(Request({"provider": "dashscope", "api_key": SECRET}))
    assert response.status == 200
    result = response_data(response)
    assert SECRET not in json.dumps(result)
    assert result["credential_ref"].startswith("ghopt_")
    return result["credential_ref"]


def payload(reference):
    return {"request_id": "mock-request", "prompt": "A woman walks in the rain.",
            "task": "T2VA", "media": [], "context": {}, "tag_contract": "gh_media_v1",
            "config": {"mode": "api", "provider": "dashscope", "model": "qwen-vl-max",
                       "credential_ref": reference}}


def assert_public(value):
    encoded = json.dumps(value, allow_nan=False)
    assert SECRET not in encoded
    for field in ('"api_key"', '"api_keys"', '"_cancel_event"', '"secret_store"', '"client"', '"session"'):
        assert field not in encoded


def test_old_payload_event_reproduces_exact_lock_failure():
    runtime_object = {"lock": threading.Lock()}
    with pytest.raises(TypeError, match="cannot pickle '_thread.lock' object"):
        copy.deepcopy(runtime_object)
    # This is the unchanged tag function called by V0.2.3.1's actual engine.
    old_payload = payload("ghopt_test_123")
    old_payload["_cancel_event"] = threading.Event()
    protection = protect_cloud_input_prompt(old_payload["prompt"], "T2VA", [])
    with pytest.raises(TypeError, match="cannot pickle '_thread.lock' object"):
        protect_cloud_payload_bindings(old_payload, protection)


@pytest.mark.parametrize("automatic", [False, True])
def test_actual_frontend_secret_and_optimize_to_real_backend(monkeypatch, backend, automatic):
    from .test_optimizer_persistence import run_panel
    frontend = run_panel(runtime=True, automatic=automatic, config={"mode": "api", "provider": "dashscope"})
    wire_secret = next(item["body"] for item in frontend["requests"] if item["url"].endswith("/secret"))
    wire_optimize = next(item["body"] for item in frontend["requests"] if item["url"].endswith("/optimize"))
    seen = []
    async def provider(config, data, *, api_key, cancel_event):
        assert type(api_key) is str and api_key == SECRET
        assert isinstance(cancel_event, threading.Event)
        assert_public(config)
        assert_public(data)
        assert EPHEMERAL_SECRET_STORE._lock is not None
        # This is precisely the transformation that used to encounter Event.
        copy.deepcopy(config)
        copy.deepcopy(data)
        seen.append(cancel_event)
        return "A cinematic paper boat sails through the rain."
    monkeypatch.setattr(backend, "_request_async", provider)
    def no_store_copy(*args, **kwargs):
        raise AssertionError("SecretStore must never be copied or pickled")
    monkeypatch.setattr(type(EPHEMERAL_SECRET_STORE), "__deepcopy__", no_store_copy, raising=False)
    monkeypatch.setattr(type(EPHEMERAL_SECRET_STORE), "__reduce_ex__", no_store_copy)
    monkeypatch.setattr(pickle, "dumps", no_store_copy)
    async def run():
        secret_response = await backend.store_prompt_optimizer_secret(Request(wire_secret))
        wire_optimize["config"]["credential_ref"] = response_data(secret_response)["credential_ref"]
        before = copy.deepcopy(wire_optimize)
        response = await backend.optimize_prompt(Request(wire_optimize))
        assert response.status == 200, response.text
        assert wire_optimize == before
        data = response_data(response)
        assert "cinematic" in data["prompt"]
        report = json.loads(data["report"])
        assert_public(report)
        assert "credential_ref" not in data["report"]
        assert len(seen) == 1
        assert not backend._ACTIVE_REQUESTS and not backend._ACTIVE_CANCEL_EVENTS
    asyncio.run(run())


@pytest.mark.parametrize("runtime", [threading.Lock(), threading.RLock(), threading.Event(),
                                     EPHEMERAL_SECRET_STORE, {"lock": threading.Lock()}])
def test_runtime_objects_rejected_before_copy_or_string_conversion(backend, runtime):
    config = {"provider": "dashscope", "client": runtime}
    with pytest.raises(ValueError):
        config_schema.normalize_optimizer_config(config)
    with pytest.raises(ValueError):
        config_schema.public_optimizer_config(config)
    with pytest.raises(ValueError, match="JSON-safe"):
        backend._prepare_prompt_optimization({**payload("ghopt_test_123"), "runtime": runtime})


def test_prepare_keeps_ref_string_and_event_separate(backend):
    request = payload("ghopt_test_123")
    before = copy.deepcopy(request)
    config, event = backend._prepare_prompt_optimization(request)
    assert isinstance(event, threading.Event)
    assert config["credential_ref"] == "ghopt_test_123"
    assert_public(config)
    assert_public(request)
    assert request == before


@pytest.mark.parametrize("case", ["expired", "wrong_provider", "no_credential", "environment"])
def test_resolution_error_and_environment_paths(monkeypatch, backend, case):
    called = []
    async def provider(config, data, *, api_key, cancel_event):
        called.append(api_key)
        assert_public(config)
        return "A woman walks in the rain."
    monkeypatch.setattr(backend, "_request_async", provider)
    async def run():
        ref = await exchange(backend)
        request = payload(ref)
        if case == "expired": EPHEMERAL_SECRET_STORE.clear()
        if case == "wrong_provider": request["config"]["provider"] = "openai"
        if case in ("no_credential", "environment"): request["config"].pop("credential_ref")
        if case == "environment": monkeypatch.setattr(config_schema, "_environment_api_key", lambda _: SECRET)
        response = await backend.optimize_prompt(Request(request))
        assert response.status == (200 if case == "environment" else 400)
        assert SECRET not in response.text and ref not in response.text
        if case in ("expired", "wrong_provider"):
            assert "session credential is missing or expired" in response.text
        if case == "no_credential": assert response_data(response)["error"] == "请配置 API Key 或对应环境变量。"
        assert called == ([SECRET] if case == "environment" else [])
    asyncio.run(run())


def test_provider_error_retains_traceback_but_redacts_key_and_ref(monkeypatch, backend, caplog):
    async def failing_provider(config, data, *, api_key, cancel_event):
        raise RuntimeError(f"Provider echoed {api_key} and {config['credential_ref']}")
    monkeypatch.setattr(backend, "_request_async", failing_provider)
    async def run():
        ref = await exchange(backend)
        response = await backend.optimize_prompt(Request(payload(ref)))
        assert response.status == 400
        assert "LLM provider request failed" in response.text
        assert "Provider echoed" not in response.text
        assert SECRET not in response.text + caplog.text
        assert ref not in response.text + caplog.text
        assert "Traceback (most recent call last)" in caplog.text
        assert "failing_provider" in caplog.text
        assert all(record.exc_info is None for record in caplog.records)
    asyncio.run(run())


def test_async_start_status_uses_same_provider_boundary(monkeypatch, backend):
    async def provider(config, data, *, api_key, cancel_event):
        assert api_key == SECRET and isinstance(cancel_event, threading.Event)
        assert_public(config)
        assert_public(data)
        return "A woman walks in the rain."
    monkeypatch.setattr(backend, "_request_async", provider)
    async def run():
        ref = await exchange(backend)
        response = await backend.start_prompt_optimization(Request(payload(ref)))
        assert response.status == 202
        await backend._ASYNC_OPTIMIZER_JOBS["mock-request"]
        response = await backend.prompt_optimization_status(Request({"request_id": "mock-request"}))
        assert response_data(response)["status"] == "success"
    asyncio.run(run())


def test_cancel_event_reaches_provider_without_serialization(monkeypatch, backend):
    started = None
    seen = []
    async def provider(config, data, *, api_key, cancel_event):
        seen.append(cancel_event)
        started.set()
        await asyncio.Future()
    monkeypatch.setattr(backend, "_request_async", provider)
    async def run():
        nonlocal started
        started = asyncio.Event()
        ref = await exchange(backend)
        task = asyncio.create_task(backend.optimize_prompt(Request(payload(ref))))
        await asyncio.wait_for(started.wait(), timeout=2)
        await backend.cancel_prompt_optimization(Request({"request_id": "mock-request"}))
        assert (await task).status == 499
        assert seen[0].is_set()
    asyncio.run(run())


def test_http_request_builder_uses_explicit_key_without_mutating_public_config(backend):
    config, _ = backend._prepare_prompt_optimization(payload("ghopt_test_123"))
    before = copy.deepcopy(config)
    url, headers, body = backend._request_parts(config, payload("ghopt_test_123"), api_key=SECRET)
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert config == before
    assert_public(config)
    assert SECRET not in json.dumps(body)


@pytest.mark.parametrize("mode", ["local", "runninghub"])
def test_legacy_dispatch_passes_runtime_arguments_separately(monkeypatch, backend, mode):
    event = threading.Event()
    request = payload("ghopt_test_123")
    config = {"mode": "local" if mode == "local" else "api", "provider": mode}
    if mode == "local":
        monkeypatch.setattr(backend, "_local_model_path", lambda _: Path("mock.gguf"))
        def generate(config, data, *, cancel_event):
            assert cancel_event is event
            assert_public(config)
            assert_public(data)
            return "mock local result"
        monkeypatch.setattr(backend, "_local_generate", generate)
    else:
        async def generate(config, data, *, api_key, cancel_event):
            assert api_key == SECRET and cancel_event is event
            assert_public(config)
            assert_public(data)
            return "mock runninghub result"
        monkeypatch.setattr(backend, "_request_runninghub", generate)
    assert asyncio.run(backend._request_async(config, request, api_key=SECRET, cancel_event=event)).startswith("mock")
