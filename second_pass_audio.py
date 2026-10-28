"""Keep the first-pass H3 soundtrack when refining the video latent."""
from __future__ import annotations

import torch
import comfy.nested_tensor
from comfy_api.latest import io

from .core import nested_av_parts, split_noise_masks
from .plugin_meta import NODE_CATEGORY


def preserve_first_pass_audio(first_pass: dict, selected_pass: dict) -> dict:
    """Return selected video with the untouched first-pass audio latent.

    A generic second sampler operates on the joint H3 video/audio latent. Its
    small denoise value can still substantially alter native generated audio.
    Do not mutate either cached input: other branches may still use them.
    """
    first_video, first_audio = nested_av_parts(first_pass)
    selected_video, selected_audio = nested_av_parts(selected_pass)
    if first_audio.shape != selected_audio.shape:
        raise ValueError("First-pass and selected-pass H3 audio latent shapes differ; cannot preserve audio.")

    result = selected_pass.copy()
    result["samples"] = comfy.nested_tensor.NestedTensor((selected_video, first_audio))
    if "gh_h3_audio_mode" in first_pass:
        result["gh_h3_audio_mode"] = first_pass["gh_h3_audio_mode"]
    else:
        result.pop("gh_h3_audio_mode", None)

    selected_video_mask, _ = split_noise_masks(selected_pass, selected_video, selected_audio)
    _, first_audio_mask = split_noise_masks(first_pass, first_video, first_audio)
    if selected_video_mask is not None or first_audio_mask is not None:
        if selected_video_mask is None:
            selected_video_mask = torch.ones_like(selected_video)
        if first_audio_mask is None:
            first_audio_mask = torch.ones_like(first_audio)
        result["noise_mask"] = comfy.nested_tensor.NestedTensor((selected_video_mask, first_audio_mask))
    else:
        result.pop("noise_mask", None)
    return result


class HuTXH3PreserveFirstPassAudioGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HuTXH3PreserveFirstPassAudioGH",
            display_name="HuTX · 二采保留首采音频",
            description="Use the selected video latent while keeping first-pass audio untouched.",
            category=NODE_CATEGORY + "/Utilities",
            inputs=[
                io.Latent.Input("first_pass_latent"),
                io.Latent.Input("selected_pass_latent"),
            ],
            outputs=[io.Latent.Output("av_latent")],
        )

    @classmethod
    def execute(cls, first_pass_latent, selected_pass_latent):
        return io.NodeOutput(preserve_first_pass_audio(first_pass_latent, selected_pass_latent))
