from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg.prompt_optimizer import engine
from hutx_minimax_h3_testpkg.prompt_optimizer.config_schema import public_optimizer_config
from hutx_minimax_h3_testpkg.prompt_optimizer.template_manager import (
    CLOUD_TAG_CONTRACT,
    OptimizerTagValidationError,
    protect_cloud_input_prompt,
    restore_cloud_prompt,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_JS = PROJECT_ROOT / "web" / "js" / "prompt_optimizer_shared.js"


def _fake_legacy_module(monkeypatch):
    module_name = "hutx_minimax_h3_testpkg.prompt_optimizer.legacy"
    fake = types.ModuleType(module_name)
    fake._format_prompt_sections = lambda value: value
    fake._strip_filenames = lambda value: value
    fake._ensure_fl2va_picture_labels = lambda value, task, duration, language: value
    fake._ensure_supplied_dialogues = lambda value, prompt, language: value
    fake._normalize_subject_shorthand = lambda value: value
    monkeypatch.setitem(sys.modules, module_name, fake)


def _optimize(monkeypatch, *, task: str, prompt: str, media: list[dict], llm_result):
    _fake_legacy_module(monkeypatch)

    async def fake_provider(config, payload, *, cancel_event=None):
        assert payload["context"]["tag_contract"] == CLOUD_TAG_CONTRACT
        return llm_result(payload) if callable(llm_result) else llm_result

    monkeypatch.setattr(engine, "request_optimized_prompt", fake_provider)
    return asyncio.run(
        engine.optimize_payload(
            {"provider": "test", "model": "test", "output_language": "English"},
            {
                "prompt": prompt,
                "task": task,
                "duration": 5,
                "media": media,
                "context": {},
                "tag_contract": CLOUD_TAG_CONTRACT,
            },
        )
    )


def test_cloud_t2v_uses_common_optimizer_engine(monkeypatch):
    result = _optimize(
        monkeypatch,
        task="T2VA",
        prompt="A paper boat crosses a puddle.",
        media=[],
        llm_result="A cinematic paper boat crosses a rain-lit puddle.",
    )
    assert result == "A cinematic paper boat crosses a rain-lit puddle."


def test_cloud_i2v_picture_tag_is_protected_and_restored_in_place(monkeypatch):
    result = _optimize(
        monkeypatch,
        task="I2VA",
        prompt="<Picture 1> begins to move.",
        media=[{"kind": "image", "label": "<Picture 1>"}],
        llm_result=lambda payload: payload["prompt"].replace(
            "begins to move", "starts walking"
        ),
    )
    assert result == "<Picture 1> starts walking."


def test_cloud_optimizer_accepts_provider_echo_of_connected_label(monkeypatch):
    result = _optimize(
        monkeypatch,
        task="I2VA",
        prompt="<Picture 1> begins to move.",
        media=[{"kind": "image", "label": "<Picture 1>"}],
        llm_result="Picture 1 starts walking.",
    )
    assert result == "<Picture 1> starts walking."


def test_cloud_optimizer_rejects_dropped_placeholder(monkeypatch):
    with pytest.raises(OptimizerTagValidationError, match="damaged protected media label"):
        _optimize(
            monkeypatch,
            task="I2VA",
            prompt="<Picture 1> begins to move.",
            media=[{"kind": "image", "label": "<Picture 1>"}],
            llm_result="The subject begins to move.",
        )


def test_cloud_fl2v_picture_tags_keep_exact_angle_bracket_contract(monkeypatch):
    result = _optimize(
        monkeypatch,
        task="FL2VA",
        prompt="Move from <Picture 1> to <Picture 2>.",
        media=[
            {"kind": "image", "label": "<Picture 1>"},
            {"kind": "image", "label": "<Picture 2>"},
        ],
        llm_result=lambda payload: payload["prompt"].replace("Move", "Transition"),
    )
    assert "<Picture 1>" in result
    assert "<Picture 2>" in result


def test_cloud_ref2v_tags_remain_provider_neutral_and_dense(monkeypatch):
    media = [
        {"kind": "image", "label": "<Picture 1>"},
        {"kind": "image", "label": "<Picture 2>"},
        {"kind": "video", "label": "<Video 1>"},
        {"kind": "audio", "label": "<Audio 1>"},
    ]
    result = _optimize(
        monkeypatch,
        task="Ref2VA",
        prompt="Use <Picture 1>, <Picture 2>, <Video 1>, and <Audio 1>.",
        media=media,
        llm_result=lambda payload: payload["prompt"].replace("Use", "Stage with"),
    )
    for tag in ("<Picture 1>", "<Picture 2>", "<Video 1>", "<Audio 1>"):
        assert tag in result
    assert "Image 1" not in result


def test_cloud_tag_preparation_is_task_aware_without_calling_a_provider():
    protected = protect_cloud_input_prompt(
        "Transition from Picture 1 to Picture 2.",
        "fl2v",
        [{"label": "<Picture 1>"}, {"label": "<Picture 2>"}],
    )
    assert protected.active_tags == ("<Picture 1>", "<Picture 2>")
    assert "<Picture 1>" not in protected.protected_prompt
    assert "__GH_MEDIA_V1_PICTURE_1_" in protected.protected_prompt
    assert restore_cloud_prompt(protected.protected_prompt, protected) == (
        "Transition from <Picture 1> to <Picture 2>."
    )


def test_cloud_optimizer_disabled_preserves_prompt_and_enabled_uses_result(monkeypatch):
    class FakeNodeOutput:
        def __init__(self, *values):
            self.values = values

    fake_io = types.SimpleNamespace(ComfyNode=object, NodeOutput=FakeNodeOutput)
    fake_latest = types.ModuleType("comfy_api.latest")
    fake_latest.io = fake_io
    fake_comfy_api = types.ModuleType("comfy_api")
    fake_comfy_api.latest = fake_latest
    monkeypatch.setitem(sys.modules, "comfy_api", fake_comfy_api)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", fake_latest)
    module_name = "hutx_minimax_h3_testpkg.cloud_video_nodes"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    module = importlib.import_module(module_name)
    state = json.dumps({
        "mode": "text_keyframes",
        "prompt": "original prompt",
        "aspect": "16:9",
        "duration_seconds": 5,
        "media": [],
    })

    disabled = module.GHCloudVideoInputGH.execute(
        main_mode="text_keyframes",
        prompt="original prompt",
        aspect="16:9",
        duration_seconds=5,
        gh_cloud_state_json=state,
        optimizer_enabled=False,
        optimized_prompt="optimized prompt",
        optimizer_report="debug report",
    )
    enabled = module.GHCloudVideoInputGH.execute(
        main_mode="text_keyframes",
        prompt="original prompt",
        aspect="16:9",
        duration_seconds=5,
        gh_cloud_state_json=state,
        optimizer_enabled=True,
        optimized_prompt="optimized prompt",
        optimizer_report="debug report",
    )

    assert disabled.values[0]["input_prompt"] == "original prompt"
    assert enabled.values[0]["input_prompt"] == "optimized prompt"
    assert enabled.values[1:] == ("optimized prompt", "debug report")


def test_api_keys_are_redacted_from_public_and_serialized_frontend_state():
    public = public_optimizer_config(
        {
            "provider": "openai",
            "api_key": "top-secret",
            "api_keys": {"openai": "top-secret", "dashscope": "another-secret"},
        }
    )
    assert public["api_key"] == ""
    assert public["api_keys"] == {}
    assert public["has_api_key"] is True
    assert "top-secret" not in json.dumps(public)

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for frontend credential serialization test")
    source = SHARED_JS.read_text(encoding="utf-8").replace("export ", "")
    expression = "sanitizeOptimizerConfig({provider:'openai',api_key:'top-secret',api_keys:{openai:'top-secret'},auto_optimize:true})"
    script = f"{source}\nconsole.log(JSON.stringify({expression}));"
    completed = subprocess.run(
        [node, "--input-type=module", "-"], input=script,
        encoding="utf-8", timeout=20,
        check=True,
        capture_output=True,
        text=True,
    )
    serialized = json.loads(completed.stdout)
    assert "api_key" not in serialized
    assert "api_keys" not in serialized
    assert "top-secret" not in completed.stdout
    assert "api_key: apiKey" not in source
    assert "credential_ref: credentialRef" in source


def test_local_node_keeps_id_and_uses_shared_secret_sanitizer():
    source = (PROJECT_ROOT / "web" / "js" / "minimax_h3_integration.js").read_text(
        encoding="utf-8"
    )
    assert 'const NODE = "MiniMaxH3IntegrationGH"' in source
    assert "serializePublicOptimizerConfig(optimizerSettings)" in source
    assert "resolveOptimizerCredential(optimizerSettings)" in source
    assert "registerEphemeralOptimizerSecret" in source


def test_cloud_optimizer_ui_exposes_the_shared_configuration_fields():
    source = SHARED_JS.read_text(encoding="utf-8")
    for label in (
        "Optimization mode",
        "Provider",
        "API Key",
        "Maximum output tokens",
        "Output language",
        "Read visual references",
        "Automatic optimization before run",
    ):
        assert label in source
