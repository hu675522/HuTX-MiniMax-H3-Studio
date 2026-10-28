from __future__ import annotations

import importlib
import json
import sys
import types

import pytest

from hutx_minimax_h3_testpkg.engine_frontend import (
    FUSED_TURBO, HYPERFLOW, prepare_engine_plan,
)


class Output:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.expand = kwargs.get("expand")
        self.ui = kwargs.get("ui")

    def __getitem__(self, index):
        return self.args[index]


class Graph:
    def __init__(self):
        self.nodes = {}

    def node(self, kind, **inputs):
        key = str(len(self.nodes))
        self.nodes[key] = {"class_type": kind, "inputs": inputs}
        return types.SimpleNamespace(out=lambda index: [key, index])

    def finalize(self):
        return self.nodes


@pytest.fixture
def dual(monkeypatch):
    selections = {
        "diffusion_models": ["fused.safetensors", "base-ref2va.safetensors"],
        "text_encoders": ["clip.safetensors"],
        "vae": ["video.safetensors", "audio.safetensors"],
        "loras": ["hyperflow.safetensors"],
    }
    folder = types.ModuleType("folder_paths")
    folder.get_filename_list = lambda name: selections[name]
    monkeypatch.setitem(sys.modules, "folder_paths", folder)
    latest = types.ModuleType("comfy_api.latest")
    latest.io = types.SimpleNamespace(ComfyNode=object, NodeOutput=Output)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    graph = types.ModuleType("comfy_execution.graph_utils")
    graph.GraphBuilder = Graph
    monkeypatch.setitem(sys.modules, "comfy_execution.graph_utils", graph)
    key = "hutx_minimax_h3_testpkg.dual_engine_nodes"
    monkeypatch.delitem(sys.modules, key, raising=False)
    return importlib.import_module(key)


def config(engine_mode, **extra):
    return {
        "engine_mode": engine_mode,
        "fused_model_name": "fused.safetensors",
        "hyperflow_base_model": "base-ref2va.safetensors",
        "hyperflow_weights": "hyperflow.safetensors",
        "hyperflow_strength": 1.0,
        "strict_architecture": True,
        "clip_name": "clip.safetensors",
        "video_vae_name": "video.safetensors",
        "audio_vae_name": "audio.safetensors",
        "aspect": "16:9",
        "megapixels": 0.5,
        "duration_seconds": 5,
        "prompt": "A subject speaks.",
        **extra,
    }


def kinds(graph):
    return [node["class_type"] for node in graph.values()]


def terminal_config(graph):
    terminal = next(n for n in graph.values() if n["class_type"] == "GHLocalVideoDualEngineOutputGH")
    return json.loads(terminal["inputs"]["configuration"])


def test_engine_plan_forces_hyperflow_8_steps_and_disables_sla():
    plan = prepare_engine_plan(
        engine_mode=HYPERFLOW, fused_model_name="fused", hyperflow_base_model="base",
        hyperflow_weights="hf", hyperflow_strength=1.0, strict_architecture=True,
        chunk_ffn_enabled=True, chunk_count=4, chunk_threshold=4096,
        sla_enabled=True, fused_steps=4, shift_video=99, shift_audio=99)
    assert plan.model_name == "base" and plan.steps == 8
    assert plan.sla is False and plan.fused_checkpoint_loaded is False
    assert (plan.video_shift, plan.audio_shift) == (12.0, 3.0)


def test_fused_lazy_graph_never_instantiates_hyperflow(dual):
    graph = dual.GHLocalVideoInputDualEngineGH.execute(**config(FUSED_TURBO)).expand
    assert graph["0"] == {"class_type": "UNETLoader", "inputs": {"unet_name": "fused.safetensors", "weight_dtype": "default"}}
    assert "MiniMaxChunkFeedForward" in kinds(graph)
    assert "H3SLAAttention" in kinds(graph)
    assert "MiniMaxH3DualClockT8GH" in kinds(graph)
    assert "HuTXH3HyperFlowPatch" not in kinds(graph)
    assert "HuTXH3HyperFlowSampler" not in kinds(graph)
    report = terminal_config(graph)
    assert report["engine"] == "fused" and report["steps"] == 4
    assert report["fused_checkpoint_loaded"] is True


def test_hyperflow_lazy_graph_never_instantiates_fused_or_sla(dual):
    graph = dual.GHLocalVideoInputDualEngineGH.execute(**config(
        HYPERFLOW, main_mode="all_reference", ref_image_1="subject.png")).expand
    assert graph["0"] == {"class_type": "UNETLoader", "inputs": {"unet_name": "base-ref2va.safetensors", "weight_dtype": "default"}}
    assert "MiniMaxChunkFeedForward" in kinds(graph)
    assert "H3SLAAttention" not in kinds(graph)
    assert "MiniMaxH3DualClockT8GH" not in kinds(graph)
    assert "HuTXH3HyperFlowPatch" in kinds(graph)
    assert "HuTXH3HyperFlowSampler" in kinds(graph)
    report = terminal_config(graph)
    assert report["engine"] == "hyperflow" and report["steps"] == 8
    assert report["fused_checkpoint_loaded"] is False and report["sla"] == "off"


@pytest.mark.parametrize("engine", [FUSED_TURBO, HYPERFLOW])
def test_driver_audio_contract_is_engine_independent(dual, monkeypatch, engine):
    state = {"mode": "all_reference" if engine == HYPERFLOW else "text_keyframes",
             "prompt": "Speak", "media": [["ref_image_1", {"name": "face.png", "kind": "image"}]] if engine == HYPERFLOW else []}
    report = {"source_seconds": 4.0, "slot": "ref_audio_1", "audio_file": "adopted.wav"}
    monkeypatch.setattr(dual, "_prepare_local_state", lambda **kwargs:
                        (state, "ref2va" if engine == HYPERFLOW else "t2va", 5, 5, 1, report, None))
    graph = dual.GHLocalVideoInputDualEngineGH.execute(**config(engine, driver_audio={"waveform": "mock"})).expand
    integration = next(n for n in graph.values() if n["class_type"] == "MiniMaxH3IntegrationGH")
    assert integration["inputs"]["audio_mode"] == "lock_source"
    assert terminal_config(graph)["driver_audio"] == report


def test_outputs_are_transparent_and_continuation_is_only_prepared(dual):
    result = dual.GHLocalVideoInputDualEngineGH.execute(
        **config(FUSED_TURBO, continuation_latent={"samples": "previous"}))
    assert len(result.args) == 10
    graph = result.expand
    assert all(kind not in kinds(graph) for kind in (
        "RandomNoise", "BasicGuider", "SamplerCustomAdvanced", "MiniMaxH3AVDecodeT8GH",
        "CreateVideo", "SaveVideo", "VOSR2Upscale"))
    assert terminal_config(graph)["continuation"] == "prepared"


def test_terminal_report_and_exact_driver_passthrough(dual, monkeypatch):
    verifier = []
    speech = types.ModuleType("hutx_minimax_h3_testpkg.speech_bridge")
    speech.verify_locked_bundle = lambda bundle, report: verifier.append((bundle, report))
    monkeypatch.setitem(sys.modules, speech.__name__, speech)
    integration = {"width": 864, "height": 480, "length": 124, "report": "ok"}
    cfg = {"engine": "fused", "driver_audio": {"slot": "hybrid_audio"}}
    result = dual.GHLocalVideoDualEngineOutputGH.execute(
        "MODEL", "COND", "LATENT", "SAMPLER", "SIGMAS", "VVAE", "AVAE",
        "EXACT_AUDIO", integration, json.dumps(cfg), "sampler ok")
    assert result.args[:8] == ("MODEL", "COND", "LATENT", "SAMPLER", "SIGMAS", "VVAE", "AVAE", "EXACT_AUDIO")
    report = json.loads(result[8])
    assert report["resolution"] == "864x480" and report["frame_count"] == 124
    assert report["driver_audio"]["lock_source_verified"] is True
    assert verifier
