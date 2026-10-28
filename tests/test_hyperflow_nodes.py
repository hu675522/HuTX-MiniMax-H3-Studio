from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest
import torch

from hutx_minimax_h3_testpkg import hyperflow_nodes as hyperflow


ROOT = Path(__file__).resolve().parents[1]


def test_hyperflow_schemas_preserve_legacy_node_ids_and_hutx_category(monkeypatch):
    monkeypatch.setattr(hyperflow, "_lora_files", lambda: ["hyperflow.safetensors"])
    compatibility = hyperflow.H3HyperFlowCompatibilityGH.define_schema()
    patch = hyperflow.H3HyperFlowPatchGH.define_schema()
    sampler = hyperflow.H3HyperFlowSamplerGH.define_schema()

    assert compatibility.node_id == "HuTXH3HyperFlowCompatibility"
    assert patch.node_id == "HuTXH3HyperFlowPatch"
    assert sampler.node_id == "HuTXH3HyperFlowSampler"
    assert {compatibility.category, patch.category, sampler.category} == {
        "HuTX/MiniMax H3 Studio/HyperFlow"
    }
    assert [item.id for item in patch.inputs] == [
        "model", "hyperflow_weights", "strength", "strict_architecture"
    ]
    assert [item.id for item in sampler.inputs] == ["model", "av_latent"]
    assert [item.id for item in sampler.outputs] == ["model", "sampler", "sigmas", "report"]


def test_hyperflow_sigma_metadata_validation():
    assert hyperflow._meta_sigmas({}) == hyperflow.DEFAULT_RAW_SIGMAS
    assert hyperflow._meta_sigmas({"hyperflow_sigmas": "[1, 0.5, 0]"}) == (1.0, 0.5, 0.0)
    for invalid in ("[]", "[1]", "[1, 0.5, 0.6, 0]", "[1, 0.5, 0.1]"):
        with pytest.raises(ValueError):
            hyperflow._meta_sigmas({"hyperflow_sigmas": invalid})


def test_shifted_clock_math_has_expected_endpoints_and_finite_slope():
    sigma = torch.tensor([1.0, 0.5, 0.0])
    shifted = hyperflow._shift_sigma(sigma, 12.0)
    assert torch.allclose(shifted[[0, -1]], torch.tensor([1.0, 0.0]))
    audio = hyperflow._time_shift_sigma(shifted, 12.0, 3.0)
    assert torch.allclose(audio[[0, -1]], torch.tensor([1.0, 0.0]))
    slope = hyperflow._time_shift_slope(shifted, 12.0, 3.0)
    assert torch.isfinite(slope).all() and torch.all(slope > 0)


@pytest.mark.parametrize(
    ("prefix", "suffix", "offset"),
    [
        ("transformer.transformer_blocks.0.attn.to_q", "blocks.0.attn.qkv_proj.weight", 0),
        ("transformer.transformer_blocks.0.attn.to_k", "blocks.0.attn.qkv_proj.weight", 2),
        ("transformer.transformer_blocks.0.attn.to_v", "blocks.0.attn.qkv_proj.weight", 4),
        ("transformer.token_refiner.refiner_blocks.0.attn.to_out.0", "token_refiner.blocks.0.attn.out_proj.weight", None),
    ],
)
def test_hyperflow_maps_attention_targets(prefix, suffix, offset):
    key = "diffusion_model." + suffix
    A, B = torch.randn(1, 4), torch.randn(2, 1)
    target, mapped_a, mapped_b = hyperflow._map_module(prefix, {key}, A, B)
    assert mapped_a is A and mapped_b is B
    if offset is None:
        assert target == key
    else:
        assert target == (key, (0, offset, 2))


def test_hyperflow_swaps_swiglu_halves_for_h3_fc1():
    key = "diffusion_model.blocks.0.mlp.fc1.weight"
    A = torch.randn(1, 4)
    B = torch.tensor([[1.0], [2.0], [3.0], [4.0]])
    target, _, mapped_b = hyperflow._map_module(
        "transformer.transformer_blocks.0.ff.net.0.proj", {key}, A, B
    )
    assert target == key
    assert mapped_b[:, 0].tolist() == [3.0, 4.0, 1.0, 2.0]


def test_cleanup_fix_keeps_low_rank_weights_out_of_module_state():
    class Base(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.freq_dim = 4
            self.proj_in = torch.nn.Linear(4, 4)
            self.proj_out = torch.nn.Linear(4, 4)

    def low_rank():
        return hyperflow._LowRank(torch.randn(1, 4), torch.randn(4, 1), 1.0)

    wrapper = hyperflow.HyperFlowTimeEmbedder(
        Base(), 0.5, low_rank(), low_rank(), low_rank(), low_rank()
    )
    state_keys = set(wrapper.state_dict())
    assert state_keys == {
        "proj_in.weight", "proj_in.bias", "proj_out.weight", "proj_out.bias"
    }
    assert all("_hf_" not in name for name, _ in wrapper.named_modules())
    assert all("_hf_" not in name for name, _ in wrapper.named_buffers())


def test_dual_clock_sampler_steps_both_modalities_and_resets_context(monkeypatch):
    monkeypatch.setattr(hyperflow.comfy.utils, "model_trange", lambda count, disable=None: range(count))
    monkeypatch.setattr(hyperflow, "to_d", lambda x, sigma, denoised: torch.ones_like(x))
    callbacks = []
    seen_contexts = []

    def model(x, sigma, **kwargs):
        seen_contexts.append(hyperflow._HYPERFLOW_STEP.get())
        return torch.zeros_like(x)

    x = torch.zeros(1, 6)
    sigmas = torch.tensor([1.0, 0.5, 0.0])
    output = hyperflow._sample_hyperflow_dual_clock(
        model, x, sigmas, callback=callbacks.append,
        audio_values=2, shift_video=12.0, shift_audio=3.0,
    )
    assert output.shape == x.shape
    assert len(callbacks) == 2 and len(seen_contexts) == 2
    assert all(isinstance(item, hyperflow.StepContext) for item in seen_contexts)
    assert hyperflow._HYPERFLOW_STEP.get() is None
    assert torch.isfinite(output).all()


def test_source_has_no_network_or_process_execution_and_registers_in_extension():
    source = (ROOT / "hyperflow_nodes.py").read_text(encoding="utf-8")
    assert all(token not in source for token in ("requests.", "urllib.", "subprocess", "os.system"))
    tree = ast.parse((ROOT / "nodes.py").read_text(encoding="utf-8"))
    extension = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MiniMaxH3IntegrationExtension")
    returned = next(node for node in ast.walk(extension) if isinstance(node, ast.Return))
    ids = [item.id for item in returned.value.elts]
    assert ids[-3:] == [
        "H3HyperFlowCompatibilityGH", "H3HyperFlowPatchGH", "H3HyperFlowSamplerGH"
    ]
