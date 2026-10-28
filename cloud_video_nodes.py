from __future__ import annotations

import json

from comfy_api.latest import io

from .gh_video_request import build_cloud_video_request


from .plugin_meta import NODE_CATEGORY as PLUGIN_CATEGORY

NODE_CATEGORY = PLUGIN_CATEGORY + "/Cloud"
CLOUD_ASPECT_OPTIONS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
MEDIA_SLOTS = [
    "first_frame",
    "last_frame",
    "hybrid_audio",
    *(f"ref_image_{index}" for index in range(1, 10)),
    *(f"ref_video_{index}" for index in range(1, 4)),
    *(f"ref_audio_{index}" for index in range(1, 4)),
]


def _hidden_string(name: str, *, default: str = ""):
    return io.String.Input(
        name,
        default=default,
        optional=True,
        extra_dict={"hidden": True},
    )


def _hidden_boolean(name: str, *, default: bool = False):
    return io.Boolean.Input(name, default=default, extra_dict={"hidden": True})


class GHCloudVideoInputGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="GHCloudVideoInputGH",
            display_name="HuTX Cloud Video Input · 5-in-1",
            description=(
                "Provider-neutral cloud video request input. It stores only prompt, "
                "ComfyUI input-relative media names, and lightweight metadata; it does "
                "not load local video models or build conditioning."
            ),
            category=NODE_CATEGORY,
            inputs=[
                io.Combo.Input(
                    "main_mode",
                    options=["text_keyframes", "all_reference"],
                    default="text_keyframes",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "prompt",
                    multiline=True,
                    dynamic_prompts=True,
                    default="",
                    extra_dict={"hidden": True},
                ),
                io.Combo.Input(
                    "aspect",
                    options=CLOUD_ASPECT_OPTIONS,
                    default="adaptive",
                    extra_dict={"hidden": True},
                ),
                io.Float.Input(
                    "duration_seconds",
                    default=5.0,
                    min=0.1,
                    max=120.0,
                    step=1.0,
                    round=0.01,
                    extra_dict={"hidden": True},
                ),
                *(_hidden_string(slot) for slot in MEDIA_SLOTS),
                _hidden_string("gh_cloud_state_json"),
                _hidden_boolean("optimizer_enabled"),
                _hidden_string("optimized_prompt"),
                _hidden_string("optimizer_report"),
            ],
            outputs=[
                io.Custom("GHVideoRequest").Output("request"),
                io.String.Output("optimized_prompt"),
                io.String.Output("optimizer_report"),
            ],
        )

    @classmethod
    def execute(
        cls,
        main_mode,
        prompt,
        aspect,
        duration_seconds,
        first_frame="",
        last_frame="",
        hybrid_audio="",
        ref_image_1="",
        ref_image_2="",
        ref_image_3="",
        ref_image_4="",
        ref_image_5="",
        ref_image_6="",
        ref_image_7="",
        ref_image_8="",
        ref_image_9="",
        ref_video_1="",
        ref_video_2="",
        ref_video_3="",
        ref_audio_1="",
        ref_audio_2="",
        ref_audio_3="",
        gh_cloud_state_json="",
        optimizer_enabled=False,
        optimized_prompt="",
        optimizer_report="",
    ):
        media_values = {
            "first_frame": first_frame,
            "last_frame": last_frame,
            "hybrid_audio": hybrid_audio,
            "ref_image_1": ref_image_1,
            "ref_image_2": ref_image_2,
            "ref_image_3": ref_image_3,
            "ref_image_4": ref_image_4,
            "ref_image_5": ref_image_5,
            "ref_image_6": ref_image_6,
            "ref_image_7": ref_image_7,
            "ref_image_8": ref_image_8,
            "ref_image_9": ref_image_9,
            "ref_video_1": ref_video_1,
            "ref_video_2": ref_video_2,
            "ref_video_3": ref_video_3,
            "ref_audio_1": ref_audio_1,
            "ref_audio_2": ref_audio_2,
            "ref_audio_3": ref_audio_3,
        }
        effective_prompt = (
            str(optimized_prompt)
            if bool(optimizer_enabled) and str(optimized_prompt or "")
            else str(prompt or "")
        )
        effective_state_json = gh_cloud_state_json
        if effective_prompt != str(prompt or "") and gh_cloud_state_json not in {"", "(none)"}:
            try:
                state = json.loads(gh_cloud_state_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                state = None
            if isinstance(state, dict):
                state = dict(state)
                state["prompt"] = effective_prompt
                effective_state_json = json.dumps(state, ensure_ascii=False)
        request = build_cloud_video_request(
            main_mode=main_mode,
            input_prompt=effective_prompt,
            aspect=aspect,
            duration_seconds=duration_seconds,
            media_values=media_values,
            gh_cloud_state_json=effective_state_json,
        )
        return io.NodeOutput(request, str(optimized_prompt or ""), str(optimizer_report or ""))
