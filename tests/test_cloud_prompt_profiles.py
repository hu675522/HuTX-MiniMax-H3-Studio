from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg.prompt_optimizer import config_schema, engine, profiles
from hutx_minimax_h3_testpkg.prompt_optimizer.template_manager import protect_cloud_input_prompt, OptimizerTagValidationError
from hutx_minimax_h3_testpkg.fal_models import resolve_h3_endpoint, FalValidationError
from .test_optimizer_runtime_serialization import backend, Request, exchange
from .test_optimizer_persistence import config_response_from_actual_handler, run_panel, run_shared

ROOT = Path(__file__).resolve().parents[1]
AUDIT = json.loads((ROOT / "tests/fixtures/cloud_prompt_abc_audit.json").read_text(encoding="utf-8"))


def payload(task):
    labels = {"t2v":[],"i2v":["<Picture 1>"],"fl2v":["<Picture 1>","<Picture 2>"],"ref2v":["<Picture 1>","<Video 1>","<Audio 1>"]}[task]
    return {"tag_contract":"gh_media_v1", "task":task, "duration":5,
            "prompt":" ".join(labels) + " A woman walks toward the camera.",
            "media":[{"label":label,"kind":"image" if "Picture" in label else "video" if "Video" in label else "audio"} for label in labels]}


@pytest.mark.parametrize("variant,task,expected", [
    *[(variant,task,"concise") for variant in ("H3 Max", "H3 Max Turbo") for task in ("t2v","i2v","fl2v")],
    ("H3 Max","ref2v","structured"),
])
def test_auto_mapping_supported_models(variant, task, expected):
    assert resolve_h3_endpoint(variant, task)
    assert profiles.resolve_prompt_profile({}, payload(task)) == ("auto", expected)
    js = run_shared(f'console.log(resolveCloudPromptProfile("auto", {json.dumps(task)}));').stdout.strip()
    assert js == expected


def test_turbo_ref2v_capability_error_stays_fal_owned():
    with pytest.raises(FalValidationError): resolve_h3_endpoint("H3 Max Turbo", "ref2v")


@pytest.mark.parametrize("task", ["t2v","i2v","fl2v","ref2v"])
@pytest.mark.parametrize("profile", ["concise","structured"])
def test_explicit_override(task, profile):
    assert profiles.resolve_prompt_profile({"prompt_profile":profile},payload(task)) == (profile,profile)


@pytest.mark.parametrize("task", ["t2v","i2v","fl2v","ref2v"])
def test_concise_independent_template_and_protected_output(task, backend, monkeypatch):
    data = payload(task)
    protected = protect_cloud_input_prompt(data["prompt"],task,data["media"])
    output = protected.protected_prompt + " Preserve identity and clothing. Use plausible movement and a slow push-in."
    config = {"mode":"api","provider":"dashscope","protocol":"openai","api_url":"https://mock.invalid/v1","model":"mock-model","prompt_profile":"concise","output_language":"English","read_media":True}
    captured = {}
    async def provider(config, prepared, **kwargs):
        captured.update(prepared)
        _, _, wire = backend._request_parts(config, prepared, api_key="TEST_KEY")
        instruction = wire["messages"][0]["content"]
        assert "CONCISE profile" in instruction
        assert "50–100" in instruction and "100–220" in instruction
        assert "not truncation limits" in instruction
        assert "unless explicitly requested" in instruction
        assert "Return exactly these" not in instruction
        return output
    monkeypatch.setattr(engine,"request_optimized_prompt",provider)
    result = asyncio.run(engine.optimize_payload(config,data))
    assert result == data["prompt"].strip() + " Preserve identity and clothing. Use plausible movement and a slow push-in."
    assert captured["context"]["resolved_prompt_profile"] == "concise"
    assert data["prompt"] == payload(task)["prompt"]
    assert all(label["label"] in result for label in data["media"])
    assert "__GH" not in result and "overall_soundscape" not in result


@pytest.mark.parametrize("read_media", [False,True])
@pytest.mark.parametrize("protocol", ["openai","gemini","responses"])
def test_concise_read_media_keeps_provider_transport(backend, read_media, protocol):
    data = payload("i2v")
    protection = protect_cloud_input_prompt(data["prompt"],"i2v",data["media"])
    placeholder = next(iter(protection.placeholders_by_tag.values()))
    data["prompt"] = protection.protected_prompt
    data["media"] = [{"kind":"image","label":placeholder,"images":["data:image/png;base64,AAAA"]}]
    data["context"] = {"tag_contract":"gh_media_v1","resolved_prompt_profile":"concise"}
    config={"provider":"dashscope","protocol":protocol,"model":"mock-model","api_url":"https://mock.invalid/v1","read_media":read_media}
    _,_,body=backend._request_parts(config,data,api_key="TEST_KEY")
    encoded=json.dumps(body)
    assert "CONCISE profile" in encoded and placeholder in encoded
    assert ("AAAA" in encoded) == read_media


def test_concise_runninghub_uses_same_system_dispatch(backend, monkeypatch):
    data=payload("i2v")
    data["context"]={"tag_contract":"gh_media_v1","resolved_prompt_profile":"concise"}
    actual=backend._system_prompt
    class StopBeforeNetwork(Exception): pass
    def capture(*args):
        assert "CONCISE profile" in actual(*args)
        raise StopBeforeNetwork()
    monkeypatch.setattr(backend,"_system_prompt",capture)
    with pytest.raises(StopBeforeNetwork): asyncio.run(backend._request_runninghub({"provider":"runninghub"},data,api_key="TEST_KEY"))


@pytest.mark.parametrize("case", ["missing","unknown"])
def test_concise_keeps_missing_unknown_label_rejection(backend, monkeypatch, case):
    data=payload("i2v")
    async def provider(config, prepared):
        return "A woman walks." if case == "missing" else prepared["prompt"] + " <Picture 2>"
    monkeypatch.setattr(engine,"request_optimized_prompt",lambda config,prepared,**kwargs:provider(config,prepared))
    with pytest.raises(OptimizerTagValidationError): asyncio.run(engine.optimize_payload({"prompt_profile":"concise"},data))


def test_no_substring_truncation_and_no_structured_disguise():
    long="The camera moves slowly. " * 80
    assert profiles.validate_concise_output(long) == long.strip()
    with pytest.raises(ValueError,match="Structured section headings"):
        profiles.validate_concise_output(AUDIT["prompts"]["structured"]["text"])


@pytest.mark.parametrize("task", ["i2v","ref2v"])
def test_structured_engine_output_compatibility(backend, monkeypatch, task):
    data=payload(task)
    async def provider(config,prepared,**kwargs):
        context=prepared["context"]
        assert context["resolved_prompt_profile"]=="structured"
        system=backend._system_prompt(task.upper()+"A",5,[],"English",context)
        assert "CONCISE profile" not in system and "overall_soundscape" in system
        return prepared["prompt"]
    monkeypatch.setattr(engine,"request_optimized_prompt",provider)
    actual=asyncio.run(engine.optimize_payload({"prompt_profile":"structured"},data))
    assert all(item["label"] in actual for item in data["media"])
    assert "overall_soundscape" in backend._system_prompt(task,5,[],"English",{"tag_contract":"gh_media_v1"})


@pytest.mark.parametrize("profile", [None,"auto","concise","structured"])
def test_local_legacy_ignores_cloud_profile(backend, monkeypatch, profile):
    data={"task":"T2VA","prompt":"A woman walks.","media":[]}
    config={} if profile is None else {"prompt_profile":profile}
    assert profiles.resolve_prompt_profile(config,data)==("structured","structured")
    called=[]
    original=backend._format_prompt_sections
    def format_sections(text): called.append(text);return original(text)
    async def provider(config,prepared,**kwargs):
        assert "resolved_prompt_profile" not in prepared.get("context",{})
        return "A woman walks."
    monkeypatch.setattr(backend,"_format_prompt_sections",format_sections)
    monkeypatch.setattr(engine,"request_optimized_prompt",provider)
    asyncio.run(engine.optimize_payload(config,data))
    assert called==["A woman walks."]


@pytest.mark.parametrize("profile", ["auto","concise","structured"])
def test_backend_config_roundtrip_and_report_fields(profile, backend, monkeypatch):
    config={"provider":"dashscope","prompt_profile":profile}
    assert config_schema.normalize_optimizer_config(config)["prompt_profile"]==profile
    assert backend._normalize_config(config)["prompt_profile"]==profile
    result=json.loads(engine.optimizer_report(config=config,payload=payload("i2v"),status="optimized"))
    assert result["requested_prompt_profile"]==profile
    assert result["resolved_prompt_profile"]==("concise" if profile=="auto" else profile)


def test_actual_optimize_route_profile_and_security(backend, monkeypatch):
    async def provider(config,data,**kwargs):
        assert config["prompt_profile"]=="concise"
        assert data["context"]["resolved_prompt_profile"]=="concise"
        return data["prompt"]
    monkeypatch.setattr(backend,"_request_async",provider)
    async def run():
        ref=await exchange(backend)
        request=payload("i2v")
        request["config"]={"provider":"dashscope","credential_ref":ref,"prompt_profile":"concise"}
        response=await backend.optimize_prompt(Request(request))
        assert response.status==200
        assert ref not in response.text and "TEST_SECRET_123" not in response.text
        report=json.loads(json.loads(response.text)["report"])
        assert report["resolved_prompt_profile"]=="concise"
    asyncio.run(run())


@pytest.mark.parametrize("profile", ["auto","concise","structured"])
@pytest.mark.parametrize("automatic", [False,True])
def test_ui_manual_auto_history_and_serialization(profile, automatic, monkeypatch):
    config=config_response_from_actual_handler(monkeypatch)
    result=run_panel(config=config,runtime=True,locale="zh",profile=profile,automatic=automatic)
    state=result["state"]["optimizer"]
    assert state["config"]["prompt_profile"]==profile
    assert result["runtime"]["reopenedProfile"]==profile
    assert state["original_prompt"]=="A paper boat sails."
    assert state["optimized_prompt"]=="Optimized paper boat scene."
    report=json.loads(state["optimizer_report"])
    assert report["requested_prompt_profile"]==profile
    assert report["resolved_prompt_profile"]==("concise" if profile=="auto" else profile)
    wire=next(r["body"] for r in result["requests"] if r["url"].endswith("/optimize"))
    assert wire["config"]["prompt_profile"]==profile
    assert "api_key" not in json.dumps(wire)
    assert "TEST_SECRET_123" not in json.dumps(result["state"])


def test_old_workflow_default_auto_and_live_mode_recommendation(monkeypatch):
    config=config_response_from_actual_handler(monkeypatch)
    state={"schema_version":1,"mode":"text_keyframes","prompt":"A woman walks.","aspect":"16:9","duration_seconds":5,"media":[["ref_image_1",{"name":"image.png"}]],"optimizer":{}}
    result=run_panel(state=state,config=config,locale="zh",profileActions=[{"type":"snapshot"},{"type":"mode","index":1},{"type":"profile","value":"concise"},{"type":"profile","value":"auto"},{"type":"mode","index":0}])
    snapshots=result["profileSnapshots"]
    assert snapshots[0]["options"]==["auto","concise","structured"]
    assert snapshots[0]["text"]==snapshots[-1]["text"]=="当前推荐：精简"
    assert snapshots[1]["text"]==snapshots[3]["text"]=="当前推荐：结构化（Ref2V）"
    assert snapshots[2]["hidden"]
    assert result["state"]["optimizer"]["config"]["prompt_profile"]=="auto"


def test_invalid_profile_rejected_in_both_persistence_boundaries():
    with pytest.raises(ValueError): profiles.normalize_prompt_profile("balanced")
    with pytest.raises(FalValidationError): config_schema.serialize_public_optimizer_config({"prompt_profile":"balanced"})
    result=run_shared('try { serializePublicOptimizerConfig({prompt_profile:"balanced"}); } catch(e) { console.log("rejected"); }')
    assert result.stdout.strip()=="rejected"


def test_audit_real_prompts_only_offline_design_evidence():
    assert [AUDIT["prompts"][p]["subjective_score"] for p in ("raw","concise","structured")]==[84,93,93]
    assert "two natural steps" in AUDIT["prompts"]["concise"]["text"]
    assert "overall_soundscape" in AUDIT["prompts"]["structured"]["text"]
    assert all("<Picture 1>" in item["text"] for item in AUDIT["prompts"].values())
    assert "cloud_prompt_abc_audit" not in (ROOT/"prompt_optimizer/profiles.py").read_text(encoding="utf-8")
