from __future__ import annotations

import time

from comfy_api.latest import io, ui
from comfy_api.latest._input_impl import VideoFromFile

from .fal_h3_max import FalH3MaxService
from .fal_models import DEFAULT_MODEL_VARIANT, H3_MODEL_REGISTRY
from .gh_video_request import normalize_video_request


from .plugin_meta import NODE_CATEGORY as PLUGIN_CATEGORY

NODE_CATEGORY = PLUGIN_CATEGORY + "/Cloud"
MINIMAX_INPUT_TYPE = io.Custom("MiniMax")
GH_VIDEO_REQUEST_INPUT_TYPE = io.Custom("GHVideoRequest")


class FalH3MaxVideoGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="FalH3MaxVideoGH",
            display_name="HuTX · MiniMax H3 Max / Turbo",
            description=(
                "Route either a Legacy MiniMax integration or provider-neutral GHVideoRequest "
                "to fal MiniMax H3 Max or H3 Max Turbo. "
                "Use dry_run first; it never uploads or submits a generation."
            ),
            category=NODE_CATEGORY,
            not_idempotent=True,
            is_output_node=True,
            inputs=[
                io.MultiType.Input(
                    "integration",
                    types=[MINIMAX_INPUT_TYPE, GH_VIDEO_REQUEST_INPUT_TYPE],
                    display_name="request / integration",
                ),
                io.Combo.Input(
                    "model_variant",
                    options=list(H3_MODEL_REGISTRY),
                    default=DEFAULT_MODEL_VARIANT,
                    optional=True,
                    display_name="model",
                ),
                io.Combo.Input(
                    "execution_mode",
                    options=["dry_run", "generate"],
                    default="dry_run",
                ),
                io.Combo.Input("resolution", options=["480P", "768P"], default="768P"),
                io.Combo.Input(
                    "prompt_expansion_mode",
                    options=["balanced", "quality"],
                    default="balanced",
                ),
                io.Int.Input("seed", default=-1, min=-1, max=2147483647, step=1),
                io.Boolean.Input("enable_safety_checker", default=True),
                io.Float.Input(
                    "max_estimated_cost",
                    default=2.0,
                    min=0.0,
                    max=1000.0,
                    step=0.01,
                    round=0.01,
                ),
            ],
            outputs=[
                io.Video.Output("video"),
                io.String.Output("video_url"),
                io.String.Output("request_id"),
                io.String.Output("endpoint"),
                io.String.Output("report"),
                io.String.Output("expanded_prompt"),
            ],
        )

    @classmethod
    def execute(
        cls,
        integration,
        execution_mode,
        resolution,
        prompt_expansion_mode,
        seed,
        enable_safety_checker,
        max_estimated_cost,
        model_variant=DEFAULT_MODEL_VARIANT,
    ):
        node_started_at = time.perf_counter()
        normalized = normalize_video_request(integration)
        result = FalH3MaxService().run(
            normalized,
            model_variant=model_variant,
            execution_mode=execution_mode,
            resolution=resolution,
            prompt_expansion_mode=prompt_expansion_mode,
            seed=seed,
            enable_safety_checker=enable_safety_checker,
            max_estimated_cost=max_estimated_cost,
            node_started_at=node_started_at,
        )
        # ComfyUI accepts None for a typed output. In dry_run this deliberately
        # leaves VIDEO empty instead of creating a misleading placeholder file.
        video = VideoFromFile(result.local_video_path) if result.local_video_path else None
        return io.NodeOutput(
            video,
            result.video_url,
            result.request_id,
            result.endpoint,
            result.report,
            result.expanded_prompt,
            ui=ui.PreviewText(result.report),
        )
