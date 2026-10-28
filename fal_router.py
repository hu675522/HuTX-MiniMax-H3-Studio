from __future__ import annotations

import json
import math
from urllib.parse import quote

from .fal_models import (
    DEFAULT_MODEL_VARIANT,
    FalMediaUrls,
    FalPlan,
    FalValidationError,
    h3_model_config,
    resolve_h3_endpoint,
)
from .gh_video_request import (
    GH_PROMPT_TAG_SCHEME,
    LEGACY_PROMPT_TAG_SCHEME,
    NormalizedMediaEntry,
    NormalizedVideoRequest,
)
from .prompt_tags import MEDIA_TAG_RE


# Preserve the existing public constants; endpoint selection uses the registry.
MODEL_NAME = h3_model_config()["model"]
TEXT_ENDPOINT = resolve_h3_endpoint(DEFAULT_MODEL_VARIANT, "t2v")
IMAGE_ENDPOINT = resolve_h3_endpoint(DEFAULT_MODEL_VARIANT, "i2v")
REFERENCE_ENDPOINT = resolve_h3_endpoint(DEFAULT_MODEL_VARIANT, "ref2v")
REFERENCE_LIMIT = 12
SUPPORTED_ASPECT_RATIOS = {
    "21:9": 21 / 9,
    "16:9": 16 / 9,
    "4:3": 4 / 3,
    "1:1": 1.0,
    "3:4": 3 / 4,
    "9:16": 9 / 16,
}
SUPPORTED_ASPECTS = set(SUPPORTED_ASPECT_RATIOS)
ADAPTIVE_ASPECT_RELATIVE_TOLERANCE = 0.05


def _slot_number(item: NormalizedMediaEntry) -> int:
    try:
        return int(item.slot.rsplit("_", 1)[1])
    except (IndexError, TypeError, ValueError):
        raise FalValidationError(f"Invalid normalized media slot: {item.slot!r}") from None


def validate_reference_shape(request: NormalizedVideoRequest) -> None:
    images = request.reference_images
    videos = request.reference_videos
    audios = request.reference_audios
    total = len(images) + len(videos) + len(audios)
    if total > REFERENCE_LIMIT:
        raise FalValidationError(
            f"MiniMax H3 Max Reference supports at most {REFERENCE_LIMIT} total files; got {total}."
        )
    if audios and not images and not videos:
        raise FalValidationError(
            "MiniMax H3 Max Reference does not allow audio as the only reference input."
        )


def _legacy_media_ordinal_maps(
    request: NormalizedVideoRequest,
) -> tuple[dict[str, dict[int, int]], set[int]]:
    image_map: dict[int, int] = {}
    video_map: dict[int, int] = {}
    audio_map: dict[int, int] = {}
    embedded_video_audio_ordinals: set[int] = set()
    if request.resolved_task == "ref2v":
        images = sorted(request.reference_images, key=_slot_number)
        videos = sorted(request.reference_videos, key=_slot_number)
        audios = sorted(request.reference_audios, key=_slot_number)
        image_map = {_slot_number(item): dense for dense, item in enumerate(images, 1)}
        video_map = {_slot_number(item): dense for dense, item in enumerate(videos, 1)}

        # Preserve the Local H3 historical Audio N contract. Audible video
        # soundtracks occupy the early local audio ordinals, while fal's
        # Audio N namespace addresses only reference_audio_urls.
        audible_videos = [
            item for item in videos if not item.muted and item.has_audio is not False
        ]
        embedded_video_audio_ordinals = set(range(1, len(audible_videos) + 1))
        audio_map = {
            len(audible_videos) + local_dense: fal_dense
            for fal_dense, local_dense in enumerate(range(1, len(audios) + 1), 1)
        }
    return {"picture": image_map, "video": video_map, "audio": audio_map}, embedded_video_audio_ordinals


def _cloud_media_ordinal_maps(
    request: NormalizedVideoRequest,
) -> tuple[dict[str, dict[int, int]], set[int]]:
    if request.resolved_task != "ref2v":
        return {"picture": {}, "video": {}, "audio": {}}, set()
    # gh_media_v1 ordinals are positions in the active request arrays. They do
    # not inherit sparse physical slot suffixes and video soundtracks never
    # consume the explicit Audio N namespace.
    return {
        "picture": {ordinal: ordinal for ordinal in range(1, len(request.reference_images) + 1)},
        "video": {ordinal: ordinal for ordinal in range(1, len(request.reference_videos) + 1)},
        "audio": {ordinal: ordinal for ordinal in range(1, len(request.reference_audios) + 1)},
    }, set()


def adapt_prompt_for_fal(prompt: str, request: NormalizedVideoRequest) -> str:
    """Adapt the request's declared media-tag contract to fal H3 Max."""
    if request.prompt_tag_scheme == LEGACY_PROMPT_TAG_SCHEME:
        maps, embedded_video_audio = _legacy_media_ordinal_maps(request)
    elif request.prompt_tag_scheme == GH_PROMPT_TAG_SCHEME:
        maps, embedded_video_audio = _cloud_media_ordinal_maps(request)
    else:
        raise FalValidationError(
            f"Unsupported prompt tag scheme: {request.prompt_tag_scheme!r}."
        )

    keyframe_labels = {
        "i2v": {1: "the first frame"},
        "fl2v": {1: "the first frame", 2: "the last frame"},
    }

    def replacement(match) -> str:
        raw_type = (match.group(1) or match.group(3)).lower()
        media_type = "picture" if raw_type in {"image", "picture"} else raw_type
        ordinal = int(match.group(2) or match.group(4))
        if request.resolved_task in keyframe_labels and media_type == "picture":
            frame_label = keyframe_labels[request.resolved_task].get(ordinal)
            if frame_label is None:
                raise FalValidationError(
                    f"Prompt media tag {match.group(0)!r} has no active fal keyframe input."
                )
            return frame_label
        if media_type == "audio" and ordinal in embedded_video_audio:
            raise FalValidationError(
                f"Local <Audio {ordinal}> refers to a reference-video soundtrack, but fal H3 Max "
                "only exposes Audio N for reference_audio_urls. Mute that video or remove this tag."
            )
        dense = maps.get(media_type, {}).get(ordinal)
        if dense is None:
            raise FalValidationError(
                f"Prompt media tag {match.group(0)!r} has no active fal {media_type} input."
            )
        fal_type = "Image" if media_type == "picture" else media_type.title()
        return f"{fal_type} {dense}"

    return MEDIA_TAG_RE.sub(replacement, str(prompt or ""))


def dry_run_media_urls(request: NormalizedVideoRequest) -> FalMediaUrls:
    def placeholder(item: NormalizedMediaEntry | None) -> str | None:
        if item is None:
            return None
        return "fal-upload://input/" + quote(item.name, safe="/")

    return FalMediaUrls(
        first_frame=placeholder(request.first_frame),
        last_frame=placeholder(request.last_frame),
        reference_images=tuple(placeholder(item) for item in request.reference_images),
        reference_videos=tuple(placeholder(item) for item in request.reference_videos),
        reference_audios=tuple(placeholder(item) for item in request.reference_audios),
    )


def _validate_url_counts(request: NormalizedVideoRequest, urls: FalMediaUrls) -> None:
    expected = {
        "reference_images": len(request.reference_images),
        "reference_videos": len(request.reference_videos),
        "reference_audios": len(request.reference_audios),
    }
    actual = {
        "reference_images": len(urls.reference_images),
        "reference_videos": len(urls.reference_videos),
        "reference_audios": len(urls.reference_audios),
    }
    if expected != actual:
        raise FalValidationError(f"Uploaded fal media does not match normalized request: {actual} != {expected}")


def _duration_seconds(request: NormalizedVideoRequest) -> int:
    value = float(request.duration_seconds)
    if not math.isfinite(value) or not value.is_integer() or not 5 <= value <= 15:
        raise FalValidationError(
            "MiniMax H3 Max duration must be a whole number from 5 through 15 seconds."
        )
    return int(value)


def _fal_aspect(request: NormalizedVideoRequest, *, allow_adaptive: bool) -> str:
    aspect = str(request.aspect)
    if aspect in SUPPORTED_ASPECTS:
        return aspect
    if aspect != "adaptive":
        raise FalValidationError(f"MiniMax H3 Max does not support aspect {aspect!r} for this route.")
    if allow_adaptive:
        return "adaptive"
    if request.source_kind == "gh_cloud":
        return "16:9"

    if request.legacy_canvas is None:
        raise FalValidationError("Legacy adaptive T2V request is missing its local canvas.")
    width, height = request.legacy_canvas
    if width <= 0 or height <= 0:
        raise FalValidationError(f"Adaptive local canvas must be positive; got {width}x{height}.")
    local_ratio = width / height
    nearest_aspect, nearest_ratio = min(
        SUPPORTED_ASPECT_RATIOS.items(),
        key=lambda item: abs(item[1] - local_ratio),
    )
    relative_difference = abs(local_ratio - nearest_ratio) / nearest_ratio
    if relative_difference > ADAPTIVE_ASPECT_RELATIVE_TOLERANCE:
        raise FalValidationError(
            f"Adaptive local canvas {width}x{height} has local ratio {local_ratio:.6f}. "
            f"Nearest fal ratio is {nearest_aspect} ({nearest_ratio:.6f}); "
            f"difference {relative_difference:.2%} exceeds the "
            f"{ADAPTIVE_ASPECT_RELATIVE_TOLERANCE:.0%} tolerance. "
            "Select a fal-supported aspect ratio explicitly in the MiniMax input node."
        )
    return nearest_aspect


def _names(items: tuple[NormalizedMediaEntry, ...]) -> list[str]:
    return [item.name for item in items]


def _format_report(
    request: NormalizedVideoRequest,
    *,
    execution_mode: str,
    endpoint: str,
    prompt: str,
    duration: int,
    resolution: str,
    prompt_expansion_mode: str,
    payload: dict,
    model_variant: str = DEFAULT_MODEL_VARIANT,
) -> str:
    routed_aspect = payload.get("aspect_ratio", "follows first-frame image")
    aspect_reason = (
        "cloud_t2v_provider_default"
        if request.source_kind == "gh_cloud"
        and request.resolved_task == "t2v"
        and request.aspect == "adaptive"
        else "explicit_or_route_defined"
    )
    lines = [
        f"execution_mode: {execution_mode}",
        f"model: {h3_model_config(model_variant)['model']}",
        f"model_variant: {model_variant}",
        f"resolved_task: {request.resolved_task}",
        f"endpoint: {endpoint}",
        f"prompt: {prompt}",
        f"duration: {duration}",
        f"resolution: {resolution}",
        f"aspect: {routed_aspect}",
        f"source_aspect: {request.aspect}",
        f"resolved_aspect: {routed_aspect}",
        f"reason: {aspect_reason}",
        f"aspect_reason: {aspect_reason}",
        f"first frame: {request.first_frame.name if request.first_frame else '(none)'}",
        f"last frame: {request.last_frame.name if request.last_frame else '(none)'}",
        f"reference images: {json.dumps(_names(request.reference_images), ensure_ascii=False)}",
        f"reference videos: {json.dumps(_names(request.reference_videos), ensure_ascii=False)}",
        f"reference audios: {json.dumps(_names(request.reference_audios), ensure_ascii=False)}",
        f"reference total: {len(request.reference_images) + len(request.reference_videos) + len(request.reference_audios)}",
        f"prompt expansion mode: {prompt_expansion_mode}",
        f"normalization_notes: {json.dumps(list(request.validation_notes), ensure_ascii=False)}",
        "payload:",
        json.dumps(dict(payload), ensure_ascii=False, indent=2),
    ]
    return "\n".join(lines)


def build_fal_plan(
    request: NormalizedVideoRequest,
    *,
    execution_mode: str,
    resolution: str,
    prompt_expansion_mode: str,
    seed: int,
    enable_safety_checker: bool,
    media_urls: FalMediaUrls | None = None,
    model_variant: str = DEFAULT_MODEL_VARIANT,
) -> FalPlan:
    if not isinstance(request, NormalizedVideoRequest):
        raise TypeError("build_fal_plan requires NormalizedVideoRequest")
    task = request.resolved_task
    endpoint = resolve_h3_endpoint(model_variant, task)
    model = h3_model_config(model_variant)
    if request.hybrid_audio is not None:
        raise FalValidationError(
            "MiniMax H3 Max 当前没有与 Hybrid audio + keyframes 等价的 fal schema。"
        )
    if execution_mode not in {"dry_run", "generate"}:
        raise FalValidationError(f"Unknown execution_mode: {execution_mode}")
    if resolution not in {"480P", "768P"}:
        raise FalValidationError(f"Unsupported fal resolution: {resolution}")
    if prompt_expansion_mode not in {"balanced", "quality"}:
        raise FalValidationError(f"Unsupported prompt_expansion_mode: {prompt_expansion_mode}")
    if int(seed) < -1:
        raise FalValidationError("seed must be -1 or a non-negative integer")

    duration = _duration_seconds(request)
    urls = media_urls or dry_run_media_urls(request)
    _validate_url_counts(request, urls)
    prompt = adapt_prompt_for_fal(request.routing_prompt, request)
    payload: dict[str, object] = {
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "prompt_expansion_mode": prompt_expansion_mode,
        "enable_safety_checker": bool(enable_safety_checker),
        "sync_mode": False,
    }
    if int(seed) >= 0:
        payload["seed"] = int(seed)

    if task == "t2v":
        payload["aspect_ratio"] = _fal_aspect(request, allow_adaptive=False)
    elif task == "i2v":
        if not urls.first_frame or urls.last_frame:
            raise FalValidationError("I2VA requires exactly one first frame and no last frame.")
        payload["image_url"] = urls.first_frame
    elif task == "fl2v":
        if not urls.first_frame or not urls.last_frame:
            raise FalValidationError("FL2VA requires both first and last frames.")
        payload["image_url"] = urls.first_frame
        payload["end_image_url"] = urls.last_frame
    elif task == "ref2v":
        validate_reference_shape(request)
        payload["aspect_ratio"] = _fal_aspect(request, allow_adaptive=True)
        if urls.reference_images:
            payload["reference_image_urls"] = list(urls.reference_images)
        if urls.reference_videos:
            payload["reference_video_urls"] = list(urls.reference_videos)
        if urls.reference_audios:
            payload["reference_audio_urls"] = list(urls.reference_audios)
    else:
        raise FalValidationError(f"Unsupported normalized video task: {task}")

    report = _format_report(
        request,
        execution_mode=execution_mode,
        endpoint=endpoint,
        prompt=prompt,
        duration=duration,
        resolution=resolution,
        prompt_expansion_mode=prompt_expansion_mode,
        payload=payload,
        model_variant=model_variant,
    )
    return FalPlan(model["model"], task, endpoint, prompt, payload, report, model_variant)
