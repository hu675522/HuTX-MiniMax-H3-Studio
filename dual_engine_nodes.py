"""Transparent Fused/HyperFlow Local H3 engine frontend."""
from __future__ import annotations

import json
import math

import folder_paths
from comfy_api.latest import io
from comfy_execution.graph_utils import GraphBuilder

from .engine_frontend import ENGINE_MODES, FUSED_TURBO, HYPERFLOW, prepare_engine_plan
from .local_video_state import ASPECTS, MEDIA_SLOTS, execution_state, local_state
from .plugin_meta import NODE_CATEGORY


DEFAULT_FUSED = "minimax_h3_fused_refdelta_r1024_turbo8_mystic07_int8_convrot.safetensors.safetensors"
DEFAULT_HYPERFLOW_BASE = "minimax_h3_ref2va_bf16.safetensors"
DEFAULT_HYPERFLOW_WEIGHTS = "minimax_h3_hyperflow_8step_v1.0.safetensors"


def _choice(name, folder, preferred=""):
    from .nodes import _default_model
    names = folder_paths.get_filename_list(folder)
    return io.Combo.Input(name, options=names, default=_default_model(names, preferred))


def _validate_available(value, folder, label):
    if value not in folder_paths.get_filename_list(folder):
        raise ValueError(f"Dual-engine {label} is not available in the configured ComfyUI model directories.")


def _prepare_local_state(*, main_mode, prompt, gh_local_state_json, media,
                         duration_seconds, driver_audio, reference_audio_1,
                         reference_audio_2, reference_audio_3,
                         driver_model_family, driver_conflict, driver_slot):
    if set(media) - set(MEDIA_SLOTS):
        raise ValueError("Unknown Local input fields.")
    state, task = execution_state(local_state(
        gh_local_state_json, mode=main_mode, prompt=prompt, media=media))
    driver_report = None
    reference_report = None
    drive_ordinal = 1
    requested_seconds = duration_seconds
    role_audio = (reference_audio_1, reference_audio_2, reference_audio_3)
    if task == "ref2va" and any(a is not None for a in role_audio):
        from .multi_speech_bridge import bridge_references
        from .nodes import calculate_length
        state, reference_report = bridge_references(
            state, task, role_audio, duration_seconds, calculate_length)
    if driver_audio is not None and reference_report is None:
        from .speech_bridge import bridge_audio
        from .nodes import calculate_length
        state, duration_seconds, drive_ordinal, driver_report = bridge_audio(
            state, task, driver_audio, duration_seconds, driver_model_family,
            driver_conflict, driver_slot, calculate_length)
    return state, task, duration_seconds, requested_seconds, drive_ordinal, driver_report, reference_report


class GHLocalVideoInputDualEngineGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        from .nodes import DEFAULT_AUDIO_VAE, DEFAULT_CLIP, DEFAULT_VIDEO_VAE
        return io.Schema(
            node_id="GHLocalVideoInputDualEngineGH",
            display_name="HuTX · H3 双引擎视频输入 · Fused / HyperFlow",
            category=NODE_CATEGORY + "/Local", enable_expand=True,
            description="Transparent H3 engine frontend. Sampling, decode, second pass and VOSR2 remain external.",
            inputs=[
                io.Combo.Input("engine_mode", options=list(ENGINE_MODES), default=FUSED_TURBO),
                _choice("fused_model_name", "diffusion_models", DEFAULT_FUSED),
                _choice("hyperflow_base_model", "diffusion_models", DEFAULT_HYPERFLOW_BASE),
                _choice("hyperflow_weights", "loras", DEFAULT_HYPERFLOW_WEIGHTS),
                io.Float.Input("hyperflow_strength", default=1.0, min=0.0, max=1.5, step=0.05),
                io.Boolean.Input("strict_architecture", default=True),
                _choice("clip_name", "text_encoders", DEFAULT_CLIP),
                _choice("video_vae_name", "vae", DEFAULT_VIDEO_VAE),
                _choice("audio_vae_name", "vae", DEFAULT_AUDIO_VAE),
                io.Combo.Input("aspect", options=list(ASPECTS), default="adaptive"),
                io.Float.Input("megapixels", default=0.5, min=0.2, max=2.0, step=0.1, round=0.1),
                io.Int.Input("duration_seconds", default=5, min=2, max=30, step=1),
                io.Boolean.Input("chunk_ffn_enabled", default=True),
                io.Int.Input("chunk_count", default=4, min=1, max=64, step=1),
                io.Int.Input("chunk_threshold", default=4096, min=256, max=262144, step=256),
                io.Boolean.Input("sla_enabled", default=True),
                io.Float.Input("sla_sparsity", default=0.8, min=0.0, max=0.95, step=0.05),
                io.Combo.Input("sla_block_size", options=["32", "64", "128"], default="64"),
                io.Int.Input("sla_min_seq_len", default=8192, min=0, max=1000000, step=1024),
                io.Int.Input("fused_steps", default=4, min=1, max=1000),
                io.Float.Input("shift_video", default=12.0, min=0.01, max=100.0, step=0.01),
                io.Float.Input("shift_audio", default=3.0, min=0.01, max=100.0, step=0.01),
                io.Combo.Input("main_mode", options=["text_keyframes", "all_reference"], default="text_keyframes"),
                io.String.Input("prompt", default="", multiline=True),
                *[io.String.Input(slot, default="", optional=True, extra_dict={"hidden": True}) for slot in MEDIA_SLOTS],
                io.String.Input("gh_local_state_json", default="", optional=True, extra_dict={"hidden": True}),
                io.Audio.Input("driver_audio", optional=True),
                *[io.Audio.Input(f"reference_audio_{i}", optional=True) for i in (1, 2, 3)],
                io.Combo.Input("driver_model_family", options=["unconfirmed", "FL2VA", "Ref2VA"], default="unconfirmed", optional=True),
                io.Combo.Input("driver_conflict", options=["reject_conflicts", "use_connected_audio"], default="reject_conflicts", optional=True),
                io.Combo.Input("driver_slot", options=["auto", "hybrid_audio", "ref_audio_1", "ref_audio_2", "ref_audio_3"], default="auto", optional=True),
                io.Latent.Input("continuation_latent", optional=True),
                io.Image.Input("continuation_frames", optional=True),
                io.Audio.Input("continuation_audio", optional=True),
            ],
            outputs=[
                io.Model.Output("model"), io.Conditioning.Output("positive"),
                io.Latent.Output("av_latent"), io.Sampler.Output("sampler"),
                io.Sigmas.Output("sigmas"), io.Vae.Output("video_vae"),
                io.Vae.Output("audio_vae"), io.Audio.Output("driver_audio_passthrough"),
                io.String.Output("local_report"),
                io.Custom("HUTX_H3_GENERATION_CONTEXT").Output("generation_context"),
            ],
        )

    @classmethod
    def execute(cls, engine_mode, fused_model_name, hyperflow_base_model,
                hyperflow_weights, hyperflow_strength, strict_architecture,
                clip_name, video_vae_name, audio_vae_name, aspect="adaptive",
                megapixels=0.5, duration_seconds=5, chunk_ffn_enabled=True,
                chunk_count=4, chunk_threshold=4096, sla_enabled=True,
                sla_sparsity=0.8, sla_block_size="64", sla_min_seq_len=8192,
                fused_steps=4, shift_video=12.0, shift_audio=3.0,
                main_mode="text_keyframes", prompt="", gh_local_state_json="",
                driver_audio=None, reference_audio_1=None, reference_audio_2=None,
                reference_audio_3=None, driver_model_family="unconfirmed",
                driver_conflict="reject_conflicts", driver_slot="auto",
                continuation_latent=None, continuation_frames=None,
                continuation_audio=None, **media):
        if aspect not in ASPECTS or not math.isfinite(float(megapixels)) or not 0.2 <= float(megapixels) <= 2.0:
            raise ValueError("Local aspect / megapixels must use the supported 0.2–2.0 MP range.")
        if type(duration_seconds) is not int or not 2 <= duration_seconds <= 30:
            raise ValueError("Local duration must be an integer from 2 to 30 seconds.")
        for value, folder, label in ((clip_name, "text_encoders", "clip_name"),
                                     (video_vae_name, "vae", "video_vae_name"),
                                     (audio_vae_name, "vae", "audio_vae_name")):
            _validate_available(value, folder, label)
        plan = prepare_engine_plan(
            engine_mode=engine_mode, fused_model_name=fused_model_name,
            hyperflow_base_model=hyperflow_base_model,
            hyperflow_weights=hyperflow_weights,
            hyperflow_strength=hyperflow_strength,
            strict_architecture=strict_architecture,
            chunk_ffn_enabled=chunk_ffn_enabled, chunk_count=chunk_count,
            chunk_threshold=chunk_threshold, sla_enabled=sla_enabled,
            fused_steps=fused_steps, shift_video=shift_video,
            shift_audio=shift_audio)
        _validate_available(plan.model_name, "diffusion_models", "selected model")
        if plan.mode == HYPERFLOW:
            _validate_available(plan.hyperflow_weights, "loras", "HyperFlow weights")
        state, task, actual_duration, requested_duration, drive_ordinal, driver_report, reference_report = _prepare_local_state(
            main_mode=main_mode, prompt=prompt, gh_local_state_json=gh_local_state_json,
            media=media, duration_seconds=duration_seconds, driver_audio=driver_audio,
            reference_audio_1=reference_audio_1, reference_audio_2=reference_audio_2,
            reference_audio_3=reference_audio_3, driver_model_family=driver_model_family,
            driver_conflict=driver_conflict, driver_slot=driver_slot)
        basename = plan.model_name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if basename.startswith("minimax_h3_fl2va_") and task == "ref2va":
            raise ValueError("Ref2VA requires a Ref2VA checkpoint; select a reference model.")
        if basename.startswith("minimax_h3_ref2va_") and task != "ref2va":
            raise ValueError("Text/keyframe modes require an FL2VA-compatible checkpoint.")

        graph = GraphBuilder()
        model = graph.node("UNETLoader", unet_name=plan.model_name, weight_dtype="default")
        engine_model = model.out(0)
        if plan.chunk_ffn:
            engine_model = graph.node("MiniMaxChunkFeedForward", model=engine_model,
                                      chunks=plan.chunk_count,
                                      seq_threshold=plan.chunk_threshold).out(0)
        if plan.mode == FUSED_TURBO and plan.sla:
            engine_model = graph.node(
                "H3SLAAttention", model=engine_model,
                sparsity_ratio=float(sla_sparsity), block_size=str(sla_block_size),
                min_seq_len=int(sla_min_seq_len), dense_last_steps=1,
                protect_audio=True, enabled=True, dense_steps="",
                dense_backend="comfy_kitchen", disable_fp16_accum=True,
                stabilize_motion=False, reference_protection="Off",
                tail_correction=False, use_int8_qk=False, engine="triton").out(0)

        kwargs = {slot: "" for slot in MEDIA_SLOTS}
        kwargs.update({slot: entry["name"] for slot, entry in state["media"]})
        integration = graph.node(
            "MiniMaxH3IntegrationGH", main_mode=state["mode"],
            prompt=state["prompt"], aspect=aspect, megapixels=megapixels,
            duration_seconds=actual_duration, clip_name=clip_name,
            video_vae_name=video_vae_name, audio_vae_name=audio_vae_name,
            task_type="auto", audio_mode="reference_only" if reference_report else "lock_source",
            audio_denoise_strength=0.0, drive_audio_ordinal=drive_ordinal,
            strict_prompt_tags=True, ref_image_size="match",
            gh_state_json=json.dumps(state, ensure_ascii=False), **kwargs)
        adapter = graph.node("MiniMaxH3IntegrationAdapterGH", integration=integration.out(0))
        if plan.mode == HYPERFLOW:
            patch = graph.node("HuTXH3HyperFlowPatch", model=engine_model,
                               hyperflow_weights=plan.hyperflow_weights,
                               strength=plan.hyperflow_strength,
                               strict_architecture=plan.strict_architecture)
            sampler = graph.node("HuTXH3HyperFlowSampler", model=patch.out(0),
                                 av_latent=adapter.out(1))
            sampler_report = sampler.out(3)
        else:
            sampler = graph.node("MiniMaxH3DualClockT8GH", model=engine_model,
                                 av_latent=adapter.out(1), steps=plan.steps,
                                 shift_video=plan.video_shift,
                                 shift_audio=plan.audio_shift,
                                 sampler_name="dual_clock_euler", scheduler="native_flow")
            sampler_report = json.dumps({"sampler": "dual_clock_euler", "scheduler": "native_flow"})

        continuation = {
            "enabled": any(v is not None for v in (continuation_latent, continuation_frames, continuation_audio)),
            "latent": continuation_latent is not None,
            "frames": continuation_frames is not None,
            "audio": continuation_audio is not None,
        }
        configuration = {
            **plan.metadata(), "task": task, "aspect": aspect,
            "megapixels": float(megapixels), "requested_seconds": requested_duration,
            "effective_seconds": actual_duration, "continuation": "prepared" if continuation["enabled"] else "off",
            "continuation_inputs": continuation,
        }
        if driver_report is not None:
            configuration["driver_audio"] = driver_report
        if reference_report is not None:
            configuration["reference_audio"] = reference_report
        terminal_inputs = dict(
            model=sampler.out(0), positive=adapter.out(0), av_latent=adapter.out(1),
            sampler=sampler.out(1), sigmas=sampler.out(2), video_vae=adapter.out(2),
            audio_vae=adapter.out(3), mux_audio=adapter.out(5),
            integration=integration.out(0), configuration=json.dumps(configuration, ensure_ascii=False),
            sampler_report=sampler_report)
        if continuation_latent is not None:
            terminal_inputs["continuation_latent"] = continuation_latent
        if continuation_frames is not None:
            terminal_inputs["continuation_frames"] = continuation_frames
        if continuation_audio is not None:
            terminal_inputs["continuation_audio"] = continuation_audio
        output = graph.node("GHLocalVideoDualEngineOutputGH", **terminal_inputs)
        return io.NodeOutput(*(output.out(i) for i in range(10)), expand=graph.finalize())


class GHLocalVideoDualEngineOutputGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="GHLocalVideoDualEngineOutputGH",
            display_name="HuTX · H3 Dual Engine Output", category=NODE_CATEGORY + "/Utilities",
            inputs=[
                io.Model.Input("model"), io.Conditioning.Input("positive"),
                io.Latent.Input("av_latent"), io.Sampler.Input("sampler"),
                io.Sigmas.Input("sigmas"), io.Vae.Input("video_vae"),
                io.Vae.Input("audio_vae"), io.Audio.Input("mux_audio"),
                io.Custom("MiniMax").Input("integration"),
                io.String.Input("configuration"), io.String.Input("sampler_report"),
                io.Latent.Input("continuation_latent", optional=True),
                io.Image.Input("continuation_frames", optional=True),
                io.Audio.Input("continuation_audio", optional=True),
            ],
            outputs=[
                io.Model.Output("model"), io.Conditioning.Output("positive"),
                io.Latent.Output("av_latent"), io.Sampler.Output("sampler"),
                io.Sigmas.Output("sigmas"), io.Vae.Output("video_vae"),
                io.Vae.Output("audio_vae"), io.Audio.Output("driver_audio_passthrough"),
                io.String.Output("local_report"),
                io.Custom("HUTX_H3_GENERATION_CONTEXT").Output("generation_context"),
            ])

    @classmethod
    def execute(cls, model, positive, av_latent, sampler, sigmas, video_vae,
                audio_vae, mux_audio, integration, configuration, sampler_report,
                continuation_latent=None, continuation_frames=None,
                continuation_audio=None):
        config = json.loads(configuration)
        if config.get("driver_audio"):
            from .speech_bridge import verify_locked_bundle
            verify_locked_bundle(integration, config["driver_audio"])
            config["driver_audio"]["lock_source_verified"] = True
        config.update({
            "resolution": f"{integration['width']}x{integration['height']}",
            "width": integration["width"], "height": integration["height"],
            "actual_megapixels": integration["width"] * integration["height"] / (1024 * 1024),
            "frame_count": integration["length"],
            "duration": integration["length"] / 24.0, "fps": 24,
            "driver_audio_state": "connected" if config.get("driver_audio") else "none",
            "fused_checkpoint_loaded_label": "YES" if config.get("fused_checkpoint_loaded") else "NO",
            "conditioning_report": integration["report"],
            "sampler_report": sampler_report,
        })
        context = {
            "metadata": {k: v for k, v in config.items() if k not in ("conditioning_report", "sampler_report")},
            "current_av_latent": av_latent,
            "conditioning": positive,
            "previous_av_latent": continuation_latent,
            "previous_end_frames": continuation_frames,
            "previous_end_audio": continuation_audio,
            "seed": None, "overlap_frames": 0,
        }
        report = json.dumps(config, ensure_ascii=False, indent=2)
        exact_audio = mux_audio if config.get("driver_audio") else None
        return io.NodeOutput(model, positive, av_latent, sampler, sigmas,
                             video_vae, audio_vae, exact_audio, report, context,
                             ui={"local_report": [report]})
