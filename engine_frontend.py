"""Pure planning helpers for the Local H3 dual-engine frontend.

This module deliberately contains no ComfyUI imports.  It keeps engine
selection, defaults and report metadata testable without loading models.
"""
from __future__ import annotations

from dataclasses import dataclass


FUSED_TURBO = "fused_turbo"
HYPERFLOW = "hyperflow"
ENGINE_MODES = (FUSED_TURBO, HYPERFLOW)


@dataclass(frozen=True)
class EnginePlan:
    mode: str
    model_name: str
    steps: int
    chunk_ffn: bool
    chunk_count: int
    chunk_threshold: int
    sla: bool
    video_shift: float
    audio_shift: float
    hyperflow_weights: str = ""
    hyperflow_strength: float = 0.0
    strict_architecture: bool = False

    @property
    def fused_checkpoint_loaded(self) -> bool:
        return self.mode == FUSED_TURBO

    def metadata(self) -> dict:
        return {
            "engine": "fused" if self.mode == FUSED_TURBO else "hyperflow",
            "engine_mode": self.mode,
            "model": self.model_name,
            "steps": self.steps,
            "chunk_ffn": {
                "enabled": self.chunk_ffn,
                "chunks": self.chunk_count,
                "seq_threshold": self.chunk_threshold,
            },
            "sla": "on" if self.sla else "off",
            "video_shift": self.video_shift,
            "audio_shift": self.audio_shift,
            "hyperflow_weights": self.hyperflow_weights or None,
            "hyperflow_strength": self.hyperflow_strength if self.mode == HYPERFLOW else None,
            "strict_architecture": self.strict_architecture if self.mode == HYPERFLOW else None,
            "fused_checkpoint_loaded": self.fused_checkpoint_loaded,
        }


def prepare_engine_plan(
    *, engine_mode: str, fused_model_name: str, hyperflow_base_model: str,
    hyperflow_weights: str, hyperflow_strength: float,
    strict_architecture: bool, chunk_ffn_enabled: bool, chunk_count: int,
    chunk_threshold: int, sla_enabled: bool, fused_steps: int,
    shift_video: float, shift_audio: float,
) -> EnginePlan:
    if engine_mode not in ENGINE_MODES:
        raise ValueError(f"Unsupported H3 engine mode: {engine_mode!r}.")
    if not 1 <= int(chunk_count) <= 64:
        raise ValueError("Chunk FFN chunks must be from 1 to 64.")
    if not 256 <= int(chunk_threshold) <= 262144:
        raise ValueError("Chunk FFN sequence threshold must be from 256 to 262144.")
    if engine_mode == FUSED_TURBO:
        if not 1 <= int(fused_steps) <= 1000:
            raise ValueError("Fused DualClock steps must be from 1 to 1000.")
        return EnginePlan(
            mode=engine_mode, model_name=fused_model_name, steps=int(fused_steps),
            chunk_ffn=bool(chunk_ffn_enabled), chunk_count=int(chunk_count),
            chunk_threshold=int(chunk_threshold), sla=bool(sla_enabled),
            video_shift=float(shift_video), audio_shift=float(shift_audio),
        )
    if not hyperflow_weights:
        raise ValueError("HyperFlow weights are required in HyperFlow mode.")
    if not 0.0 <= float(hyperflow_strength) <= 1.5:
        raise ValueError("HyperFlow strength must be from 0.0 to 1.5.")
    return EnginePlan(
        mode=engine_mode, model_name=hyperflow_base_model, steps=8,
        chunk_ffn=bool(chunk_ffn_enabled), chunk_count=int(chunk_count),
        chunk_threshold=int(chunk_threshold), sla=False,
        video_shift=12.0, audio_shift=3.0,
        hyperflow_weights=hyperflow_weights,
        hyperflow_strength=float(hyperflow_strength),
        strict_architecture=bool(strict_architecture),
    )
