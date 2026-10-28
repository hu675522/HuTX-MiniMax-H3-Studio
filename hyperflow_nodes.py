from __future__ import annotations

import json
import logging
import math
import re
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors import safe_open

import folder_paths
import comfy.model_sampling
import comfy.samplers
import comfy.utils
from comfy.k_diffusion.sampling import to_d
from comfy.weight_adapter.lora import LoRAAdapter
from comfy_api.latest import io

from .core import nested_av_parts
from .plugin_meta import NODE_CATEGORY

CATEGORY = NODE_CATEGORY + "/HyperFlow"
DEFAULT_RAW_SIGMAS = (1.0, 0.931506, 0.839236, 0.703462, 0.5, 0.296538, 0.160764, 0.068494, 0.0)
DEFAULT_VIDEO_SHIFT = 12.0
DEFAULT_AUDIO_SHIFT = 3.0
_HYPERFLOW_STEP = ContextVar("hutx_hyperflow_step", default=None)

@dataclass(frozen=True)
class StepContext:
    sigma_video: float
    sigma_video_next: float
    sigma_audio: float
    sigma_audio_next: float

def _shift_sigma(sigma, shift: float):
    return shift * sigma / (1.0 + (shift - 1.0) * sigma)

def _time_shift_sigma(sigma, from_shift: float, to_shift: float):
    base_sigma = sigma / (from_shift + sigma * (1.0 - from_shift))
    return _shift_sigma(base_sigma, to_shift)

def _time_shift_slope(sigma, from_shift: float, to_shift: float):
    base_sigma = sigma / (from_shift + sigma * (1.0 - from_shift))
    numerator = to_shift * (1.0 + (from_shift - 1.0) * base_sigma) ** 2
    denominator = from_shift * (1.0 + (to_shift - 1.0) * base_sigma) ** 2
    return numerator / denominator

def _lora_files():
    try:
        return folder_paths.get_filename_list("loras")
    except Exception:
        return []

def _resolve_lora(name: str) -> str:
    return folder_paths.get_full_path_or_raise("loras", name)

def _read_meta(path: str) -> dict:
    with safe_open(path, framework="pt", device="cpu") as f:
        meta = dict(f.metadata() or {})
    if meta.get("hyperflow", "").lower() != "true":
        raise ValueError("Selected file is not a HyperFlow weights file (missing hyperflow=true metadata).")
    required = ("hyperflow_version", "hyperflow_gate", "lora_alpha", "base_model")
    missing = [k for k in required if k not in meta]
    if missing:
        raise ValueError(f"HyperFlow metadata missing: {missing}")
    return meta

def _meta_sigmas(meta: dict):
    value = meta.get("hyperflow_sigmas")
    if not value:
        return DEFAULT_RAW_SIGMAS
    parsed = json.loads(value)
    if not isinstance(parsed, list) or len(parsed) < 2:
        raise ValueError("Invalid hyperflow_sigmas metadata.")
    grid = tuple(float(x) for x in parsed)
    if abs(grid[-1]) > 1e-8 or any(grid[i + 1] >= grid[i] for i in range(len(grid) - 1)):
        raise ValueError(f"Invalid HyperFlow sigma grid: {grid}")
    return grid

def _model_state_keys(model):
    try:
        return set(model.model_state_dict().keys())
    except Exception:
        return set(model.model.state_dict().keys())

def _find_diffusion(model):
    try:
        return model.get_model_object("diffusion_model")
    except Exception as e:
        raise RuntimeError("Could not find ComfyUI MiniMax H3 diffusion_model on MODEL.") from e

def _find_key(keys: set[str], suffix: str) -> str:
    matches = [k for k in keys if k.endswith(suffix)]
    if len(matches) != 1:
        raise KeyError(f"Expected one model key ending with {suffix!r}; found {len(matches)}.")
    return matches[0]

class _LowRank:
    """Plain Python LoRA holder.

    v0.2 used nn.Module/register_buffer here. DynamicVRAM then discovered
    `time_embedder.base_l1.*` buffers and backed them up. During unpatch,
    ComfyUI restores the original TimeEmbedder first, so those synthetic
    buffer paths no longer exist. Keeping A/B as plain tensor attributes
    makes them invisible to model.named_buffers() and fixes unload/cleanup.
    """
    def __init__(self, A: torch.Tensor, B: torch.Tensor, alpha: float):
        self.A = A.detach().cpu()
        self.B = B.detach().cpu()
        self.rank = int(A.shape[0])
        self.alpha = float(alpha)
        self._cache_key = None
        self._A_dev = None
        self._B_dev = None

    def __call__(self, x):
        key = (x.device.type, x.device.index, x.dtype)
        if key != self._cache_key:
            self._A_dev = self.A.to(device=x.device, dtype=x.dtype, non_blocking=True)
            self._B_dev = self.B.to(device=x.device, dtype=x.dtype, non_blocking=True)
            self._cache_key = key
        return F.linear(F.linear(x, self._A_dev), self._B_dev) * (self.alpha / self.rank)


class HyperFlowTimeEmbedder(nn.Module):
    def __init__(self, base, gate, base_l1, base_l2, endpoint_l1, endpoint_l2):
        super().__init__()
        for attr in ("freq_dim", "proj_in", "proj_out"):
            if not hasattr(base, attr):
                raise TypeError(f"Unsupported ComfyUI H3 time embedder: missing {attr}.")

        # Keep the original public parameter names (proj_in/proj_out) instead
        # of nesting the original module under `.base`. This preserves the
        # paths DynamicVRAM expects when it restores model weights.
        self.freq_dim = int(base.freq_dim)
        self.proj_in = base.proj_in
        self.proj_out = base.proj_out
        self.gate = float(gate)

        # Plain Python objects — not registered submodules/buffers.
        object.__setattr__(self, "_hf_base_l1", base_l1)
        object.__setattr__(self, "_hf_base_l2", base_l2)
        object.__setattr__(self, "_hf_endpoint_l1", endpoint_l1)
        object.__setattr__(self, "_hf_endpoint_l2", endpoint_l2)

    def _sinusoid(self, t):
        half = self.freq_dim // 2
        freqs = torch.exp(-math.log(10000.0) * torch.arange(half, dtype=torch.float32, device=t.device) / half)
        args = t.to(torch.float32)[:, None] * freqs[None]
        return torch.cat([torch.cos(args), torch.sin(args)], dim=-1)

    def _mlp(self, t, l1, l2):
        emb = self._sinusoid(t)
        target_dtype = getattr(self.proj_in.weight, "dtype", torch.float32)
        emb = emb.to(target_dtype)
        h = self.proj_in(emb) + l1(emb)
        h = F.silu(h)
        return self.proj_out(h) + l2(h)
    @staticmethod
    def _endpoint_values(t_vals, ctx):
        t = t_vals.to(torch.float32)
        out = t.clone()
        tv, rv = 1.0 - ctx.sigma_video, 1.0 - ctx.sigma_video_next
        ta, ra = 1.0 - ctx.sigma_audio, 1.0 - ctx.sigma_audio_next
        mv = torch.isclose(t, torch.tensor(tv, device=t.device), atol=2e-5, rtol=2e-5)
        ma = torch.isclose(t, torch.tensor(ta, device=t.device), atol=2e-5, rtol=2e-5)
        out[mv] = rv
        out[ma] = ra
        return out
    def forward(self, t_vals):
        ctx = _HYPERFLOW_STEP.get()
        if ctx is None:
            raise RuntimeError("HyperFlow endpoint context missing. Use H3 HyperFlow 8-Step Sampler.")
        r_vals = self._endpoint_values(t_vals, ctx)
        t_emb = self._mlp(t_vals, self._hf_base_l1, self._hf_base_l2)
        r_emb = self._mlp(r_vals, self._hf_endpoint_l1, self._hf_endpoint_l2)
        return t_emb + self.gate * (r_emb - t_emb)

def _pair(handle, prefix):
    a, b = f"{prefix}.lora_A.weight", f"{prefix}.lora_B.weight"
    keys = set(handle.keys())
    if a not in keys or b not in keys:
        raise KeyError(f"Missing HyperFlow LoRA pair: {prefix}")
    return handle.get_tensor(a), handle.get_tensor(b)

def _adapter(A, B, alpha):
    return LoRAAdapter(set(), (B, A, float(alpha), None, None, None))

_BLOCK_RE = re.compile(r"^transformer\.(?P<root>transformer_blocks|token_refiner\.refiner_blocks)\.(?P<index>\d+)\.(?P<part>attn\.to_q|attn\.to_k|attn\.to_v|attn\.to_out\.0|ff\.net\.0\.proj|ff\.net\.2)$")

def _map_module(prefix, keys, A, B):
    m = _BLOCK_RE.match(prefix)
    if not m:
        raise KeyError(f"Unsupported HyperFlow target: {prefix}")
    idx, part = int(m.group("index")), m.group("part")
    root = f"blocks.{idx}" if m.group("root") == "transformer_blocks" else f"token_refiner.blocks.{idx}"
    if part in ("attn.to_q", "attn.to_k", "attn.to_v"):
        target = _find_key(keys, f"diffusion_model.{root}.attn.qkv_proj.weight")
        inner = int(B.shape[0])
        start = {"attn.to_q": 0, "attn.to_k": inner, "attn.to_v": inner * 2}[part]
        return (target, (0, start, inner)), A, B
    if part == "attn.to_out.0":
        return _find_key(keys, f"diffusion_model.{root}.attn.out_proj.weight"), A, B
    if part == "ff.net.0.proj":
        target = _find_key(keys, f"diffusion_model.{root}.mlp.fc1.weight")
        if B.shape[0] % 2:
            raise ValueError(f"Unexpected SwiGLU LoRA shape: {tuple(B.shape)}")
        half = B.shape[0] // 2
        B = torch.cat([B[half:], B[:half]], dim=0).contiguous()
        return target, A, B
    if part == "ff.net.2":
        return _find_key(keys, f"diffusion_model.{root}.mlp.fc2.weight"), A, B
    raise AssertionError(part)

class H3HyperFlowPatchGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HuTXH3HyperFlowPatch",
            display_name="HuTX · H3 HyperFlow · 8-Step LoRA Patch",
            description="Patch official-architecture MiniMax H3 with HyperFlow v1 weights. Use the matching HyperFlow sampler node.",
            category=CATEGORY,
            inputs=[
                io.Model.Input("model"),
                io.Combo.Input("hyperflow_weights", options=_lora_files() or ["(place HyperFlow .safetensors in models/loras)"]),
                io.Float.Input("strength", default=1.0, min=0.0, max=1.5, step=0.05),
                io.Boolean.Input("strict_architecture", default=True),
            ],
            outputs=[io.Model.Output("model"), io.String.Output("report")],
        )

    @classmethod
    def execute(cls, model, hyperflow_weights, strength=1.0, strict_architecture=True):
        path = _resolve_lora(hyperflow_weights)
        meta = _read_meta(path)
        raw_sigmas = _meta_sigmas(meta)
        gate, alpha = float(meta["hyperflow_gate"]), float(meta["lora_alpha"])
        rank = int(meta.get("lora_rank", "0") or 0)
        diffusion = _find_diffusion(model)
        if bool(getattr(diffusion, "use_adaln_curves", False)):
            raise RuntimeError("This checkpoint uses AdaLN curves. HyperFlow v1.0 requires standard H3 time_embedder architecture.")
        if not hasattr(diffusion, "time_embedder"):
            raise RuntimeError("Connected H3 model has no standard time_embedder.")
        keys = _model_state_keys(model)
        patched = model.clone()
        with safe_open(path, framework="pt", device="cpu") as handle:
            b1a, b1b = _pair(handle, "transformer.time_embedder.linear_1")
            b2a, b2b = _pair(handle, "transformer.time_embedder.linear_2")
            e1a, e1b = _pair(handle, "transformer.endpoint_time_embedder.linear_1")
            e2a, e2b = _pair(handle, "transformer.endpoint_time_embedder.linear_2")
            wrapper = HyperFlowTimeEmbedder(diffusion.time_embedder, gate, _LowRank(b1a,b1b,alpha), _LowRank(b2a,b2b,alpha), _LowRank(e1a,e1b,alpha), _LowRank(e2a,e2b,alpha))
            patched.add_object_patch("diffusion_model.time_embedder", wrapper)
            # Time-embedder LoRAs were already consumed above to build HyperFlowTimeEmbedder.
            # endpoint_time_embedder is a *virtual* module created by HyperFlow's TwoTimeEmbedder,
            # so it must not fall through to the ordinary transformer-block mapper.
            prefixes = sorted(
                k[:-len(".lora_A.weight")]
                for k in handle.keys()
                if k.startswith("transformer.")
                and k.endswith(".lora_A.weight")
                and not k.startswith("transformer.time_embedder.")
                and not k.startswith("transformer.endpoint_time_embedder.")
            )
            applied, failures = 0, []
            for prefix in prefixes:
                try:
                    A, B = _pair(handle, prefix)
                    target, A, B = _map_module(prefix, keys, A, B)
                    patched.add_patches({target: _adapter(A, B, alpha)}, strength_patch=float(strength))
                    applied += 1
                except Exception as e:
                    failures.append(f"{prefix}: {e}")
                    if strict_architecture:
                        raise RuntimeError(f"HyperFlow mapping failed at {prefix}: {e}") from e
        opts = patched.model_options.setdefault("transformer_options", {})
        opts["hutx_hyperflow"] = {"version": meta["hyperflow_version"], "gate": gate, "alpha": alpha, "rank": rank, "raw_sigmas": list(raw_sigmas), "video_shift": float(meta.get("hyperflow_video_shift", DEFAULT_VIDEO_SHIFT)), "audio_shift": float(meta.get("hyperflow_audio_shift", DEFAULT_AUDIO_SHIFT)), "weights": Path(path).name, "strength": float(strength)}
        report = (f"HyperFlow {meta['hyperflow_version']} patched (Bridge v0.3)\nweights: {Path(path).name}\nbase_model(metadata): {meta['base_model']}\nrank/alpha/gate: {rank}/{alpha}/{gate}\nschedule: {len(raw_sigmas)-1} steps\nmapped non-time targets: {applied}\nunmapped targets: {len(failures)}\nUse a fresh official-architecture H3 base/ref2va checkpoint; do not quality-test on HuTX FusedTurbo.")
        return io.NodeOutput(patched, report)

class HyperFlowSampling(comfy.model_sampling.ModelSamplingDiscreteFlow, comfy.model_sampling.CONST):
    @property
    def audio_scale(self):
        return 1.0

def _audio_velocity_is_raw(model):
    return callable(getattr(getattr(model, "model", None), "audio_scale", None))

def _sample_hyperflow_dual_clock(model, x, sigmas, extra_args=None, callback=None, disable=None, *, audio_values, shift_video, shift_audio, audio_velocity_is_raw=False):
    extra_args = {} if extra_args is None else extra_args
    packed_values = int(x.shape[-1])
    video_values = packed_values - int(audio_values)
    if video_values <= 0:
        raise ValueError(f"Bad packed H3 AV latent: packed={packed_values}, audio={audio_values}")
    denoise_mask = extra_args.get("denoise_mask")
    audio_mask = denoise_mask[..., video_values:] if denoise_mask is not None and denoise_mask.shape[-1] == packed_values else None
    s_in = x.new_ones([x.shape[0]])
    for step in comfy.utils.model_trange(len(sigmas) - 1, disable=disable):
        sv, svn = sigmas[step], sigmas[step + 1]
        sa, san = _time_shift_sigma(sv, shift_video, shift_audio), _time_shift_sigma(svn, shift_video, shift_audio)
        token = _HYPERFLOW_STEP.set(StepContext(float(sv), float(svn), float(sa), float(san)))
        try:
            denoised = model(x, sv * s_in, **extra_args)
        finally:
            _HYPERFLOW_STEP.reset(token)
        derivative = to_d(x, sv, denoised)
        slope_audio = _time_shift_slope(sv, shift_video, shift_audio)
        video_delta, audio_delta = svn - sv, san - sa
        if not audio_velocity_is_raw:
            audio_delta = audio_delta / slope_audio
        if audio_mask is not None:
            audio_delta = video_delta + audio_mask * (audio_delta - video_delta)
        if callback is not None:
            callback({"x": x, "i": step, "sigma": sv, "sigma_hat": sv, "denoised": denoised})
        x = torch.cat((x[..., :video_values] + derivative[..., :video_values] * video_delta, x[..., video_values:] + derivative[..., video_values:] * audio_delta), dim=-1)
    return x

class H3HyperFlowSamplerGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HuTXH3HyperFlowSampler",
            display_name="HuTX · H3 HyperFlow · 8-Step Dual Clock",
            description="Build the trained HyperFlow sigma grid and its MiniMax H3 video/audio dual-clock sampler.",
            category=CATEGORY,
            inputs=[io.Model.Input("model"), io.Latent.Input("av_latent")],
            outputs=[
                io.Model.Output("model"), io.Sampler.Output("sampler"),
                io.Sigmas.Output("sigmas"), io.String.Output("report"),
            ],
        )

    @classmethod
    def execute(cls, model, av_latent):
        meta = model.model_options.get("transformer_options", {}).get("hutx_hyperflow")
        if not isinstance(meta, dict):
            raise RuntimeError("MODEL has no HyperFlow metadata. Connect H3 HyperFlow Patch first.")
        raw = torch.tensor(meta["raw_sigmas"], dtype=torch.float32)
        shift_video, shift_audio = float(meta["video_shift"]), float(meta["audio_shift"])
        sigmas = _shift_sigma(raw, shift_video)
        video, audio = nested_av_parts(av_latent)
        audio_values = math.prod(audio.shape[1:])
        patched = model.clone()
        original_sampling = model.get_model_object("model_sampling")
        model_sampling = HyperFlowSampling(model.model.model_config)
        model_sampling.set_parameters(shift=shift_video)
        if hasattr(original_sampling, "noise_scale"):
            model_sampling.set_noise_scale(original_sampling.noise_scale)
        patched.add_object_patch("model_sampling", model_sampling)
        tr = patched.model_options.get("transformer_options", {}).copy()
        tr["minimax_h3_sigma_shift_video"], tr["minimax_h3_sigma_shift_audio"] = shift_video, shift_audio
        patched.model_options["transformer_options"] = tr
        raw_audio = _audio_velocity_is_raw(model)
        def sampler_function(model_wrap, x, sample_sigmas, extra_args=None, callback=None, disable=None):
            return _sample_hyperflow_dual_clock(model_wrap, x, sample_sigmas, extra_args=extra_args, callback=callback, disable=disable, audio_values=audio_values, shift_video=shift_video, shift_audio=shift_audio, audio_velocity_is_raw=raw_audio)
        sampler_function.__name__ = "sample_h3_hyperflow_8step"
        sampler = comfy.samplers.KSAMPLER(sampler_function)
        report = f"HyperFlow sampler: {len(sigmas)-1} NFE | video shift {shift_video} | audio shift {shift_audio} | video {tuple(video.shape)} | audio {tuple(audio.shape)}"
        return io.NodeOutput(patched, sampler, sigmas, report)

class H3HyperFlowCompatibilityGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HuTXH3HyperFlowCompatibility",
            display_name="HuTX · H3 HyperFlow · Compatibility Check",
            description="Check the connected MiniMax H3 architecture before applying HyperFlow weights.",
            category=CATEGORY,
            inputs=[io.Model.Input("model")],
            outputs=[io.String.Output("report")],
        )

    @classmethod
    def execute(cls, model):
        diffusion = _find_diffusion(model)
        keys = _model_state_keys(model)
        curve = bool(getattr(diffusion, "use_adaln_curves", False))
        has_time = hasattr(diffusion, "time_embedder")
        samples = ["diffusion_model.blocks.0.attn.qkv_proj.weight", "diffusion_model.blocks.0.attn.out_proj.weight", "diffusion_model.blocks.0.mlp.fc1.weight", "diffusion_model.blocks.0.mlp.fc2.weight", "diffusion_model.token_refiner.blocks.0.attn.qkv_proj.weight"]
        found = {s: any(k.endswith(s) for k in keys) for s in samples}
        compatible = has_time and not curve and all(found.values())
        lines = [f"HyperFlow bridge architecture check: {'PASS' if compatible else 'FAIL'}", f"time_embedder: {has_time}", f"use_adaln_curves: {curve}"] + [f"{k}: {v}" for k,v in found.items()]
        lines.append("PASS checks architecture only. For valid quality use a fresh official-architecture MiniMax-H3 base/ref2va checkpoint, not an already-distilled Turbo/Fused checkpoint.")
        return io.NodeOutput("\n".join(lines))
