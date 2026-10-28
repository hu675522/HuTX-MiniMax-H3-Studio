from __future__ import annotations

import importlib
import json
import logging
import math
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from .fal_api_client import FalApiClient
from .fal_credentials import redact_fal_secrets, FalLogFilter
from .fal_media import (
    FalUploadCache,
    MediaInspection,
    inspect_manifest_media,
    upload_manifest_media,
)
from .fal_models import (
    DEFAULT_MODEL_VARIANT,
    FalCostEstimate,
    FalGenerationResult,
    FalValidationError,
    estimate_h3_max_cost,
    format_h3_max_cost_report,
)
from .fal_router import build_fal_plan
from .gh_video_request import NormalizedVideoRequest


LOGGER = logging.getLogger(__name__)
LOGGER.addFilter(FalLogFilter())


class FalDownloadError(RuntimeError):
    """Remote generation succeeded, but its video could not be saved locally."""

def _download_video(video_url: str, request_id: str) -> Path:
    folder_paths = importlib.import_module("folder_paths")
    httpx = importlib.import_module("httpx")
    output_directory = Path(folder_paths.get_output_directory()).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    safe_request_id = re.sub(r"[^A-Za-z0-9._-]+", "_", request_id).strip("._") or "result"
    destination = output_directory / f"fal_h3_max_{safe_request_id}.mp4"
    temporary = destination.with_suffix(".mp4.part")
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            )
        }
        with httpx.Client(timeout=60, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", video_url) as response:
                response.raise_for_status()
                with temporary.open("wb") as target:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        if chunk:
                            target.write(chunk)
        if temporary.stat().st_size == 0:
            raise RuntimeError("fal H3 Max returned an empty video file")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _estimate_cost(
    inspection: MediaInspection,
    *,
    resolved_task: str,
    endpoint: str,
    output_duration_seconds: float,
    resolution: str,
    pricing_as_of: date | None = None,
) -> FalCostEstimate:
    image_pixels = [
        int(item.width) * int(item.height)
        for item in inspection.reference_images
        if item.width is not None and item.height is not None
    ]
    if len(image_pixels) != len(inspection.reference_images):
        raise FalValidationError("Could not estimate all reference image token counts.")
    return estimate_h3_max_cost(
        resolved_task=resolved_task,
        endpoint=endpoint,
        output_duration_seconds=output_duration_seconds,
        resolution=resolution,
        as_of=pricing_as_of,
        reference_image_pixels=image_pixels,
        reference_video_seconds=[
            float(item.effective_duration or 0.0) for item in inspection.reference_videos
        ],
        reference_audio_seconds=[
            float(item.effective_duration or 0.0) for item in inspection.reference_audios
        ],
    )


def _result_metadata(result: Mapping[str, Any]) -> tuple[str, Any, float | None]:
    expanded_value = result.get("expanded_prompt")
    expanded_prompt = "" if expanded_value is None else str(expanded_value)
    returned_seed = result.get("seed")
    server_inference_seconds: float | None = None
    timings = result.get("timings")
    if isinstance(timings, Mapping) and timings.get("inference") is not None:
        try:
            server_inference_seconds = float(timings["inference"])
        except (TypeError, ValueError):
            server_inference_seconds = None
    return expanded_prompt, returned_seed, server_inference_seconds


def _section(title: str, lines: list[str]) -> str:
    return "\n".join(["==============================", title, "==============================", *lines])


def _seconds(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.6f}s"


def _media_names(request: NormalizedVideoRequest, key: str) -> list[str]:
    return [item.name for item in getattr(request, key)]


def _format_report(
    request: NormalizedVideoRequest,
    *,
    plan,
    execution_mode: str,
    prompt_expansion_mode: str,
    estimate: FalCostEstimate,
    max_estimated_cost: float,
    timing: Mapping[str, float | None],
    request_id: str = "",
    expanded_prompt: str = "",
    returned_seed: Any = None,
    video_url: str = "",
    downloaded_file: str = "",
    status: str = "dry_run",
) -> str:
    images = _media_names(request, "reference_images")
    videos = _media_names(request, "reference_videos")
    audios = _media_names(request, "reference_audios")
    first = request.first_frame
    last = request.last_frame
    resolved_aspect = plan.payload.get("aspect_ratio", "follows first-frame image")
    aspect_reason = (
        "cloud_t2v_provider_default"
        if request.source_kind == "gh_cloud"
        and request.resolved_task == "t2v"
        and request.aspect == "adaptive"
        else "explicit_or_route_defined"
    )
    input_section = _section(
        "INPUT",
        [
            f"input_prompt: {request.input_prompt}",
            f"router_prompt: {plan.prompt}",
            f"duration: {plan.payload['duration']}",
            f"resolution: {plan.payload['resolution']}",
            f"aspect: {resolved_aspect}",
            f"source_aspect: {request.aspect}",
            f"resolved_aspect: {resolved_aspect}",
            f"reason: {aspect_reason}",
            f"aspect_reason: {aspect_reason}",
            f"first_frame: {first.name if first else '(none)'}",
            f"last_frame: {last.name if last else '(none)'}",
            f"reference_images: {json.dumps(images, ensure_ascii=False)}",
            f"reference_videos: {json.dumps(videos, ensure_ascii=False)}",
            f"reference_audios: {json.dumps(audios, ensure_ascii=False)}",
            f"reference_total: {len(images) + len(videos) + len(audios)}",
            f"source_kind: {request.source_kind}",
            f"prompt_tag_scheme: {request.prompt_tag_scheme}",
            f"normalization_notes: {json.dumps(list(request.validation_notes), ensure_ascii=False)}",
            f"prompt_expansion_mode: {prompt_expansion_mode}",
            "payload:",
            json.dumps(dict(plan.payload), ensure_ascii=False, indent=2),
        ],
    )
    timing_section = _section(
        "TIMING",
        [
            f"media_prepare_seconds: {_seconds(timing.get('media_prepare_seconds'))}",
            f"upload_seconds: {_seconds(timing.get('upload_seconds'))}",
            (
                "fal_submit_to_result_seconds: "
                f"{_seconds(timing.get('fal_submit_to_result_seconds'))}"
            ),
            (
                "fal_submit_to_result_note: wall-clock time from starting the fal "
                "submit/request operation until the completed result is returned by the fal SDK; "
                "it is not pure queue waiting time"
            ),
            f"server_inference_seconds: {_seconds(timing.get('server_inference_seconds'))}",
            f"download_seconds: {_seconds(timing.get('download_seconds'))}",
            f"fal_node_elapsed_seconds: {_seconds(timing.get('fal_node_elapsed_seconds'))}",
            (
                "workflow_total_elapsed_seconds: measured by the frontend when the Fal node's "
                "VIDEO-ready executed event arrives"
            ),
        ],
    )
    return redact_fal_secrets("\n\n".join(
        [
            _section(
                "REQUEST",
                [
                    f"execution_mode: {execution_mode}",
                    f"model: {plan.model}",
                    f"model_variant: {plan.model_variant}",
                    f"resolved_task: {plan.resolved_task}",
                    f"endpoint: {plan.endpoint}",
                    f"request_id: {request_id}",
                ],
            ),
            input_section,
            _section("SERVER EXPANDED PROMPT", ["server_expanded_prompt:", expanded_prompt]),
            timing_section,
            format_h3_max_cost_report(estimate, max_estimated_cost=max_estimated_cost),
            _section(
                "OUTPUT",
                [
                    f"status: {status}",
                    f"returned_seed: {'' if returned_seed is None else returned_seed}",
                    f"video_url: {video_url}",
                    f"downloaded_file: {downloaded_file}",
                ],
            ),
        ]
    ))


def _log_timing(timing: Mapping[str, float | None]) -> None:
    LOGGER.warning(
        "[HuTX H3 Studio] Timing\n"
        "workflow total: measured in frontend after VIDEO-ready\n"
        "fal node total: %s\n"
        "media prepare: %s\n"
        "upload: %s\n"
        "fal_submit_to_result_seconds: %s\n"
        "server inference: %s\n"
        "download: %s",
        _seconds(timing.get("fal_node_elapsed_seconds")),
        _seconds(timing.get("media_prepare_seconds")),
        _seconds(timing.get("upload_seconds")),
        _seconds(timing.get("fal_submit_to_result_seconds")),
        _seconds(timing.get("server_inference_seconds")),
        _seconds(timing.get("download_seconds")),
    )


class FalH3MaxService:
    def __init__(self, *, upload_cache: FalUploadCache | None = None):
        self.upload_cache = upload_cache

    def run(
        self,
        request: NormalizedVideoRequest,
        *,
        execution_mode: str,
        resolution: str,
        prompt_expansion_mode: str,
        seed: int,
        enable_safety_checker: bool,
        max_estimated_cost: float = 2.0,
        node_started_at: float | None = None,
        pricing_as_of: date | None = None,
        model_variant: str = DEFAULT_MODEL_VARIANT,
    ) -> FalGenerationResult:
        if not isinstance(request, NormalizedVideoRequest):
            raise TypeError("FalH3MaxService.run requires NormalizedVideoRequest")
        node_started = node_started_at if node_started_at is not None else time.perf_counter()
        timing: dict[str, float | None] = {
            "media_prepare_seconds": 0.0,
            "upload_seconds": 0.0,
            "fal_submit_to_result_seconds": None,
            "server_inference_seconds": None,
            "download_seconds": None,
            "fal_node_elapsed_seconds": None,
        }
        preview = build_fal_plan(
            request,
            model_variant=model_variant,
            execution_mode=execution_mode,
            resolution=resolution,
            prompt_expansion_mode=prompt_expansion_mode,
            seed=seed,
            enable_safety_checker=enable_safety_checker,
        )

        media_started = time.perf_counter()
        try:
            inspection = inspect_manifest_media(request)
        finally:
            timing["media_prepare_seconds"] = time.perf_counter() - media_started
        try:
            cost_limit = float(max_estimated_cost)
        except (TypeError, ValueError) as exc:
            raise FalValidationError("max_estimated_cost must be a non-negative USD amount.") from exc
        if not math.isfinite(cost_limit) or cost_limit < 0:
            raise FalValidationError("max_estimated_cost must be a non-negative USD amount.")
        estimate = _estimate_cost(
            inspection,
            resolved_task=preview.resolved_task,
            endpoint=preview.endpoint,
            output_duration_seconds=float(preview.payload["duration"]),
            resolution=resolution,
            pricing_as_of=pricing_as_of,
        )
        if execution_mode == "generate" and estimate.estimated_total_cost > cost_limit:
            precision = max(4, len(str(estimate.price_per_second).partition(".")[2]))
            raise FalValidationError(
                "Estimated fal cost exceeds max_estimated_cost; request was not submitted.\n"
                f"estimated_total_cost: ${estimate.estimated_total_cost:.{precision}f} USD\n"
                f"max_estimated_cost: ${cost_limit:.{precision}f} USD\n"
                "Increase max_estimated_cost only after reviewing the dry-run cost report."
            )
        if execution_mode == "dry_run":
            timing["fal_node_elapsed_seconds"] = time.perf_counter() - node_started
            report = _format_report(
                request,
                plan=preview,
                execution_mode=execution_mode,
                prompt_expansion_mode=prompt_expansion_mode,
                estimate=estimate,
                max_estimated_cost=cost_limit,
                timing=timing,
            )
            return FalGenerationResult(
                local_video_path=None,
                video_url="",
                request_id="",
                endpoint=preview.endpoint,
                report=report,
                expanded_prompt="",
                payload=preview.payload,
            )

        # Authentication, SDK import, uploads, and generation all happen only
        # after the local inspection and cost guard have passed.
        client = FalApiClient()
        urls = upload_manifest_media(
            inspection,
            uploader=client.upload_file,
            cache=self.upload_cache,
            timing=timing,
        )
        plan = build_fal_plan(
            request,
            model_variant=model_variant,
            execution_mode=execution_mode,
            resolution=resolution,
            prompt_expansion_mode=prompt_expansion_mode,
            seed=seed,
            enable_safety_checker=enable_safety_checker,
            media_urls=urls,
        )

        def record_request_id(request_id: str) -> None:
            LOGGER.warning(
                "[HuTX H3 Studio] Submit\nmodel_variant: %s\nendpoint: %s\nrequest_id: %s",
                model_variant,
                plan.endpoint,
                request_id,
            )

        submit_started = time.perf_counter()
        try:
            queued = client.submit_and_wait(
                plan.endpoint,
                plan.payload,
                on_submitted=record_request_id,
            )
        finally:
            timing["fal_submit_to_result_seconds"] = time.perf_counter() - submit_started
        expanded_prompt, returned_seed, server_inference_seconds = _result_metadata(queued.result)
        timing["server_inference_seconds"] = server_inference_seconds
        video = queued.result.get("video")
        video_url = video.get("url") if isinstance(video, Mapping) else None
        if not isinstance(video_url, str) or not video_url:
            raise RuntimeError(
                "fal H3 Max result is missing result['video']['url'].\n"
                f"Request ID: {queued.request_id}"
            )
        generation_summary = "\n".join([
            "Generation completed successfully.",
            f"Request ID: {queued.request_id}",
            f"Remote video: {video_url}",
        ])
        LOGGER.warning(
            "[HuTX H3 Studio] Generation complete\nrequest_id: %s\n"
            "server inference: %s\nvideo_url: %s",
            queued.request_id,
            _seconds(server_inference_seconds),
            video_url,
        )
        download_started = time.perf_counter()
        try:
            local_path = _download_video(video_url, queued.request_id)
        except Exception as exc:
            timing["download_seconds"] = time.perf_counter() - download_started
            timing["fal_node_elapsed_seconds"] = time.perf_counter() - node_started
            failure_report = _format_report(
                request,
                plan=plan,
                execution_mode=execution_mode,
                prompt_expansion_mode=prompt_expansion_mode,
                estimate=estimate,
                max_estimated_cost=cost_limit,
                timing=timing,
                request_id=queued.request_id,
                expanded_prompt=expanded_prompt,
                returned_seed=returned_seed,
                video_url=video_url,
                status="generation_succeeded_remote_download_failed",
            )
            failure_report = "\n\n".join(
                [
                    failure_report,
                    _section(
                        "DOWNLOAD FAILURE",
                        [
                            "remote_generation: succeeded",
                            "local_download: failed",
                            f"download_error: {redact_fal_secrets(exc)}",
                            "recovery: use video_url directly; do not resubmit solely for this error",
                        ],
                    ),
                ]
            )
            message = "\n".join(
                [
                    generation_summary,
                    "Remote generation has already succeeded and incurred fal generation cost, "
                    "but the local download failed.",
                    f"Download error: {redact_fal_secrets(exc)}",
                    "Do not resubmit solely because of this download error; use the remote video URL.",
                    "",
                    failure_report,
                ]
            )
            LOGGER.error(message)
            _log_timing(timing)
            return FalGenerationResult(
                local_video_path=None,
                video_url=video_url,
                request_id=queued.request_id,
                endpoint=plan.endpoint,
                report=failure_report,
                expanded_prompt=expanded_prompt,
                payload=plan.payload,
            )
        timing["download_seconds"] = time.perf_counter() - download_started
        timing["fal_node_elapsed_seconds"] = time.perf_counter() - node_started
        LOGGER.warning(
            "[HuTX H3 Studio] Download complete\nlocal file: %s",
            local_path,
        )
        _log_timing(timing)
        LOGGER.warning(
            "[HuTX H3 Studio] Cost\nestimated: %s$%.5f USD\npricing model: %s\npricing endpoint: %s",
            "~" if estimate.approximate else "",
            estimate.estimated_total_cost,
            estimate.pricing_model,
            estimate.pricing_endpoint,
        )
        report = _format_report(
            request,
            plan=plan,
            execution_mode=execution_mode,
            prompt_expansion_mode=prompt_expansion_mode,
            estimate=estimate,
            max_estimated_cost=cost_limit,
            timing=timing,
            request_id=queued.request_id,
            expanded_prompt=expanded_prompt,
            returned_seed=returned_seed,
            video_url=video_url,
            downloaded_file=str(local_path),
            status="generation_succeeded_video_ready",
        )
        return FalGenerationResult(
            local_video_path=str(local_path),
            video_url=video_url,
            request_id=queued.request_id,
            endpoint=plan.endpoint,
            report=report,
            expanded_prompt=expanded_prompt,
            payload=plan.payload,
        )
