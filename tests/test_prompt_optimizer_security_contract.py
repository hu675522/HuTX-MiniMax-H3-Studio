from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg.fal_router import build_fal_plan
from hutx_minimax_h3_testpkg.gh_video_request import (
    build_cloud_video_request,
    normalize_cloud_request,
)
from hutx_minimax_h3_testpkg.prompt_optimizer.engine import optimizer_report
from hutx_minimax_h3_testpkg.prompt_optimizer.secrets import (
    EPHEMERAL_SECRET_STORE,
    EphemeralSecretStore,
    OptimizerCredentialError,
    redact_secret_text,
)
from hutx_minimax_h3_testpkg.prompt_optimizer.template_manager import (
    CLOUD_TAG_CONTRACT,
    OptimizerTagValidationError,
    protect_cloud_input_prompt,
    restore_cloud_prompt,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_JS = PROJECT_ROOT / "web" / "js" / "prompt_optimizer_shared.js"
CLOUD_JS = PROJECT_ROOT / "web" / "js" / "gh_cloud_video_input.js"
LOCAL_JS = PROJECT_ROOT / "web" / "js" / "minimax_h3_integration.js"
SECRET = "sk-audit-secret-value"
OPAQUE_REF = "ghopt_opaque-reference-only"


def _run_shared_js(expression: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for frontend security-contract tests")
    source = SHARED_JS.read_text(encoding="utf-8").replace("export ", "")
    script = f"{source}\nconsole.log(JSON.stringify({expression}));"
    completed = subprocess.run(
        [node, "--input-type=module", "-"], input=script,
        encoding="utf-8", timeout=20,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _snapshot(task: str, raw_prompt: str, media: list[dict], media_values: dict):
    protection = protect_cloud_input_prompt(raw_prompt, task, media)
    protected = protection.protected_prompt
    llm_output = protected.replace("Use", "Cinematically use").replace("Move", "Flow")
    optimized = restore_cloud_prompt(llm_output, protection)
    main_mode = "all_reference" if task.lower().startswith("ref") else "text_keyframes"
    request = build_cloud_video_request(
        main_mode=main_mode,
        input_prompt=optimized,
        aspect="adaptive",
        duration_seconds=5,
        media_values=media_values,
    )
    normalized = normalize_cloud_request(request)
    plan = build_fal_plan(
        normalized,
        execution_mode="dry_run",
        resolution="480P",
        prompt_expansion_mode="balanced",
        seed=-1,
        enable_safety_checker=True,
    )
    return protection, protected, optimized, request, plan


def test_ephemeral_secret_store_is_process_memory_and_provider_bound():
    store = EphemeralSecretStore(ttl_seconds=60)
    reference = store.put("openai", SECRET)
    assert reference.startswith("ghopt_")
    assert SECRET not in reference
    assert store.resolve(reference, "openai") == SECRET
    with pytest.raises(OptimizerCredentialError, match="missing or expired"):
        store.resolve(reference, "dashscope")
    store.clear()
    with pytest.raises(OptimizerCredentialError, match="missing or expired"):
        store.resolve(reference, "openai")


def test_ephemeral_reference_resolves_only_at_provider_boundary(monkeypatch):
    import sys
    import types

    from hutx_minimax_h3_testpkg.prompt_optimizer.config_schema import (
        normalize_optimizer_config,
    )

    module_name = "hutx_minimax_h3_testpkg.prompt_optimizer.legacy"
    fake = types.ModuleType(module_name)
    fake._normalize_config = lambda data: {
        "mode": str(data.get("mode") or "api"),
        "provider": str(data.get("provider") or "openai"),
        "api_key": str(data.get("api_key") or ""),
        "api_keys": {},
    }
    monkeypatch.setitem(sys.modules, module_name, fake)
    EPHEMERAL_SECRET_STORE.clear()
    reference = EPHEMERAL_SECRET_STORE.put("openai", SECRET)
    config = normalize_optimizer_config(
        {"mode": "api", "provider": "openai", "credential_ref": reference}
    )
    from hutx_minimax_h3_testpkg.prompt_optimizer.provider_adapter import resolve_optimizer_api_key
    assert "api_key" not in config
    assert config["credential_ref"] == reference
    assert resolve_optimizer_api_key(config) == SECRET
    EPHEMERAL_SECRET_STORE.clear()


def test_serialized_workflow_queue_and_history_never_contain_secret_or_reference():
    result = _run_shared_js(
        "(() => {"
        "rememberOptimizerCredentials({provider:'openai',credential_ref:'" + OPAQUE_REF + "'});"
        "const runtime=withMemoryOptimizerCredentials({provider:'openai',api_key:'" + SECRET + "',auto_optimize:true});"
        "const state={optimizer:{config:sanitizeOptimizerConfig(runtime)},prompt:'hello'};"
        "const queue={prompt:{'1':{inputs:{gh_cloud_state_json:JSON.stringify(state),optimizer_report:'ok'}}}};"
        "const workflow={nodes:[{properties:{gh_cloud_video_state:JSON.stringify(state)},widgets_values:[JSON.stringify(state)]}]};"
        "const history={prompt:queue.prompt,outputs:{}};"
        "return {runtime,state,queue,workflow,history};"
        "})()"
    )
    assert result["runtime"]["credential_ref"] == OPAQUE_REF
    assert "api_key" not in result["runtime"]
    for key in ("state", "queue", "workflow", "history"):
        serialized = json.dumps(result[key])
        assert SECRET not in serialized
        assert OPAQUE_REF not in serialized
        assert "credential_ref" not in serialized


def test_normal_optimizer_payload_contains_only_opaque_reference():
    result = _run_shared_js(
        "(() => {"
        "rememberOptimizerCredentials({provider:'openai',credential_ref:'" + OPAQUE_REF + "'});"
        "return {config:withMemoryOptimizerCredentials({provider:'openai',model:'gpt'})};"
        "})()"
    )
    serialized = json.dumps(result)
    assert SECRET not in serialized
    assert result["config"]["credential_ref"] == OPAQUE_REF
    assert "api_key" not in result["config"]


def test_frontend_secret_is_not_stored_or_logged_by_workflow_code():
    shared = SHARED_JS.read_text(encoding="utf-8")
    local = LOCAL_JS.read_text(encoding="utf-8")
    cloud = CLOUD_JS.read_text(encoding="utf-8")
    assert "credentialReferenceMemory" in shared
    assert "credentialMemory" not in shared
    assert "`${OPTIMIZER_ROUTE}/secret`" in shared
    assert "localStorage" not in shared + cloud
    assert not re.search(
        r"localStorage[^\n]*(?:api[_ ]?key|credential|optimizer)", local, re.IGNORECASE
    )
    assert "sessionStorage" not in shared + local + cloud
    assert "console.log" not in shared
    assert "body.api_key = key.value" not in local
    assert "api_keys: { ...providerApiKeys }" not in local


def test_gh_video_request_and_optimizer_report_do_not_contain_secret():
    request = build_cloud_video_request(
        main_mode="text_keyframes",
        input_prompt="A cloud moves.",
        aspect="16:9",
        duration_seconds=5,
        media_values={},
    )
    report = optimizer_report(
        config={"mode": "api", "provider": "openai", "model": "gpt", "api_key": SECRET},
        payload={"task": "T2VA", "media": [], "tag_contract": CLOUD_TAG_CONTRACT},
        status="optimized",
    )
    assert SECRET not in json.dumps(request)
    assert SECRET not in report
    assert "api_key" not in request
    assert "api_key" not in request["metadata"]


def test_exception_and_log_formatter_redacts_credentials():
    value = redact_secret_text(
        f"failed Authorization: Bearer {SECRET}; url=https://example.test/?key={SECRET}",
        (SECRET,),
    )
    assert SECRET not in value
    assert value.count("[REDACTED]") >= 1


def test_i2v_tag_contract_snapshot():
    protection, protected, optimized, request, plan = _snapshot(
        "I2VA",
        "Move from <Picture 1> while preserving the subject.",
        [{"kind": "image", "label": "<Picture 1>"}],
        {"first_frame": "frames/first.png"},
    )
    assert protection.canonical_prompt.startswith("Move from <Picture 1>")
    assert "<Picture 1>" not in protected and "__GH_MEDIA_V1_PICTURE_1_" in protected
    assert optimized.startswith("Flow from <Picture 1>")
    assert request["input_prompt"] == optimized
    assert request["prompt_tag_scheme"] == "gh_media_v1"
    assert "the first frame" in plan.prompt
    assert "Picture 1" not in plan.prompt


def test_fl2v_tag_contract_snapshot():
    protection, protected, optimized, request, plan = _snapshot(
        "FL2VA",
        "Move from <Picture 1> and land exactly on <Picture 2>.",
        [
            {"kind": "image", "label": "<Picture 1>"},
            {"kind": "image", "label": "<Picture 2>"},
        ],
        {"first_frame": "frames/first.png", "last_frame": "frames/last.png"},
    )
    assert "<Picture 1>" not in protected and "<Picture 2>" not in protected
    assert optimized == "Flow from <Picture 1> and land exactly on <Picture 2>."
    assert request["input_prompt"] == optimized
    assert "the first frame" in plan.prompt and "the last frame" in plan.prompt


def test_ref2v_tag_contract_snapshot():
    raw = (
        "Use <Picture 1> and <Picture 2> as character references. "
        "Follow the motion of <Video 1>. Match <Audio 1>."
    )
    protection, protected, optimized, request, plan = _snapshot(
        "Ref2VA",
        raw,
        [
            {"kind": "image", "label": "<Picture 1>"},
            {"kind": "image", "label": "<Picture 2>"},
            {"kind": "video", "label": "<Video 1>"},
            {"kind": "audio", "label": "<Audio 1>"},
        ],
        {
            "ref_image_1": "refs/one.png",
            "ref_image_3": "refs/two.png",
            "ref_video_2": "refs/motion.mp4",
            "ref_audio_3": "refs/voice.wav",
        },
    )
    assert all(tag not in protected for tag in protection.active_tags)
    assert all(tag in optimized for tag in protection.active_tags)
    assert request["input_prompt"] == optimized
    assert request["prompt_tag_scheme"] == "gh_media_v1"
    assert "Image 1" in plan.prompt and "Image 2" in plan.prompt
    assert "Video 1" in plan.prompt and "Audio 1" in plan.prompt
    assert "<Picture" not in plan.prompt


def test_placeholder_damage_and_extra_media_tags_fail_instead_of_guessing():
    protection = protect_cloud_input_prompt(
        "Use <Picture 1> here.",
        "I2VA",
        [{"kind": "image", "label": "<Picture 1>"}],
    )
    with pytest.raises(OptimizerTagValidationError, match="damaged protected media label"):
        restore_cloud_prompt("Use the picture here.", protection)
    with pytest.raises(OptimizerTagValidationError, match="inactive media label"):
        restore_cloud_prompt(protection.protected_prompt + " <Picture 2>", protection)

    with pytest.raises(OptimizerTagValidationError, match="missing: <Picture 1>"):
        protect_cloud_input_prompt(
            "Move the supplied subject.",
            "I2VA",
            [{"kind": "image", "label": "<Picture 1>"}],
        )


def test_provider_visible_labels_restore_only_connected_media():
    media = [
        {"kind": "image", "label": "<Picture 1>"},
        {"kind": "video", "label": "<Video 1>"},
        {"kind": "audio", "label": "<Audio 1>"},
    ]
    protection = protect_cloud_input_prompt(
        "Use <Picture 1>, <Video 1>, and <Audio 1>.", "Ref2VA", media
    )
    video_token = protection.placeholders_by_tag["<Video 1>"]
    result = restore_cloud_prompt(
        f"Use Image 1 as the subject, {video_token} for movement, and <audio 1> for voice.",
        protection,
    )
    assert result == "Use <Picture 1> as the subject, <Video 1> for movement, and <Audio 1> for voice."
    with pytest.raises(OptimizerTagValidationError, match="inactive media label: <Audio 2>"):
        restore_cloud_prompt("Use <Picture 1>, <Video 1>, <Audio 1>, and <Audio 2>.", protection)
    with pytest.raises(OptimizerTagValidationError, match="damaged protected media label <Video 1>"):
        restore_cloud_prompt("Use <Picture 1> and <Audio 1>.", protection)


def test_placeholder_prose_order_can_change_while_media_identities_remain():
    protection = protect_cloud_input_prompt(
        "Start at <Picture 1>. End at <Picture 2>.",
        "FL2VA",
        [
            {"kind": "image", "label": "<Picture 1>"},
            {"kind": "image", "label": "<Picture 2>"},
        ],
    )
    first = protection.placeholders_by_tag["<Picture 1>"]
    last = protection.placeholders_by_tag["<Picture 2>"]
    reordered_result = f"End at {last}. Start at {first}."
    assert restore_cloud_prompt(reordered_result, protection) == "End at <Picture 2>. Start at <Picture 1>."
