from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
SUPPORTED_TASKS = {"t2va", "i2va", "l2va", "fl2va", "ref2va"}

DEFAULT_MODEL_VARIANT = "H3 Max"
H3_MODEL_REGISTRY = {
    "H3 Max": {
        "model": "MiniMax H3 Max",
        "endpoints": {
            "t2v": "minimax/h3-max/text-to-video",
            "i2v": "minimax/h3-max/image-to-video",
            "fl2v": "minimax/h3-max/image-to-video",
            "ref2v": "minimax/h3-max/reference-to-video",
        },
    },
    "H3 Max Turbo": {
        "model": "MiniMax H3 Max Turbo",
        "endpoints": {
            "t2v": "minimax/h3-max-turbo/text-to-video",
            "i2v": "minimax/h3-max-turbo/image-to-video",
            "fl2v": "minimax/h3-max-turbo/image-to-video",
        },
    },
}

# Keep provider pricing in one deliberately small, endpoint-aware structure.
# fal can price or promote H3 Max routes independently, so these entries must
# not be collapsed into one model-wide rate table.
H3_MAX_PRICING = {
    "currency": "USD",
    "text-to-video": {
        "rates": {"480P": 0.0125, "768P": 0.02},
        "pricing_type": "promotion",
        "verified_on": "2026-09-05",
        "promotion_end": "2026-09-07",
        "standard_rate": {"480P": 0.05, "768P": 0.08},
        "source": "https://fal.ai/models/minimax/h3-max/text-to-video",
        "source_note": (
            "Official model page lists a 75% launch discount through 2026-09-07; "
            "standard rates resume after that date."
        ),
    },
    "image-to-video": {
        "rates": {"480P": 0.0125, "768P": 0.02},
        "pricing_type": "promotion",
        "verified_on": "2026-09-05",
        "promotion_end": "2026-09-07",
        "standard_rate": {"480P": 0.05, "768P": 0.08},
        "source": "https://fal.ai/models/minimax/h3-max/image-to-video",
        "source_note": (
            "Official model page lists a 75% launch discount through 2026-09-07; "
            "the same endpoint serves I2V and first/last-frame video."
        ),
    },
    "reference-to-video": {
        "rates": {"480P": 0.05, "768P": 0.08},
        "pricing_type": "standard_conservative",
        "verified_on": "2026-09-05",
        "promotion_end": None,
        "standard_rate": {"480P": 0.05, "768P": 0.08},
        "source": "https://fal.ai/models/minimax/h3-max/reference-to-video",
        "source_note": (
            "The official Reference page confirms $0.05/$0.08 per output second; "
            "reference-token billing is charged separately. The historical "
            "standard_conservative classification is retained for compatibility."
        ),
    },
    "reference": {
        "included_tokens": 4096.0,
        "usd_per_1000_tokens": 0.02,
        "image_pixels_per_token": 1024.0,
        "video_tokens_per_second": {
            "480P": 2886.0,
            "768P": 7459.2,
        },
        "audio_tokens_per_second": 80.0,
    },
}

# Each published route owns its own pricing entry, even when rates match.
# H3_MAX_PRICING remains available to existing Python consumers.
H3_MAX_TURBO_PRICING = {
    "currency": "USD",
    "text-to-video": {
        "rates": {"480P": 0.00625, "768P": 0.01},
        "pricing_type": "promotion",
        "verified_on": "2026-09-05",
        "promotion_end": "2026-09-07",
        "standard_rate": {"480P": 0.025, "768P": 0.04},
        "source": "https://fal.ai/models/minimax/h3-max-turbo/text-to-video",
        "source_note": (
            "Official Turbo T2V page lists 75% launch-discount rates through September 7; "
            "standard rates resume after that date. Year follows the 2026 launch; "
            "the page does not specify a cutoff timezone."
        ),
    },
    "image-to-video": {
        "rates": {"480P": 0.00625, "768P": 0.01},
        "pricing_type": "promotion",
        "verified_on": "2026-09-05",
        "promotion_end": "2026-09-07",
        "standard_rate": {"480P": 0.025, "768P": 0.04},
        "source": "https://fal.ai/models/minimax/h3-max-turbo/image-to-video",
        "source_note": (
            "Official Turbo I2V/FL2V page lists 75% launch-discount rates through September 7; "
            "standard rates resume after that date. Year follows the 2026 launch; "
            "the page does not specify a cutoff timezone."
        ),
    },
}
H3_PRICING_REGISTRY = {
    "H3 Max": H3_MAX_PRICING,
    "H3 Max Turbo": H3_MAX_TURBO_PRICING,
}


class FalValidationError(ValueError):
    """Raised when a local H3 input cannot be represented by fal H3 Max."""


def h3_model_config(model_variant: str = DEFAULT_MODEL_VARIANT) -> Mapping[str, Any]:
    try:
        return H3_MODEL_REGISTRY[model_variant]
    except (KeyError, TypeError):
        raise FalValidationError(f"Unsupported H3 model_variant: {model_variant!r}.") from None


def resolve_h3_endpoint(model_variant: str, resolved_task: str) -> str:
    config = h3_model_config(model_variant)
    if resolved_task == "l2v":
        raise FalValidationError(
            f"{config['model']} 当前未实现 Last-Frame-only 路由。\n"
            "请使用本地 H3 或其他明确支持 L2V 的模型。"
        )
    endpoint = config["endpoints"].get(resolved_task)
    if endpoint is None:
        if model_variant == "H3 Max Turbo" and resolved_task == "ref2v":
            raise FalValidationError(
                "H3 Max Turbo 当前没有公开 Reference-to-Video endpoint。\n"
                "请切换到 H3 Max 运行 Ref2V。"
            )
        raise FalValidationError(f"{config['model']} does not support task {resolved_task!r}.")
    return str(endpoint)


@dataclass(frozen=True)
class FalCostEstimate:
    output_video_cost: float
    reference_estimated_cost: float
    estimated_total_cost: float
    reference_estimated_tokens: float
    reference_billable_tokens: float
    approximate: bool
    output_approximate: bool
    reference_approximate: bool
    pricing_endpoint: str
    pricing_type: str
    pricing_verified_on: str
    pricing_note: str
    promotion_end: str | None
    pricing_model: str = "MiniMax H3 Max"
    price_per_second: float = 0.0


def _pricing_endpoint_key(endpoint: str | None, resolved_task: str) -> str:
    if endpoint:
        key = str(endpoint).rstrip("/").rsplit("/", 1)[-1]
    else:
        key = {
            "t2va": "text-to-video",
            "t2v": "text-to-video",
            "i2va": "image-to-video",
            "i2v": "image-to-video",
            "fl2va": "image-to-video",
            "fl2v": "image-to-video",
            "ref2va": "reference-to-video",
            "ref2v": "reference-to-video",
        }.get(resolved_task, "")
    if key not in {"text-to-video", "image-to-video", "reference-to-video"}:
        raise FalValidationError(f"No H3 Max pricing is configured for endpoint {endpoint!r}.")
    return key


def _active_output_pricing(
    endpoint: str | None,
    resolved_task: str,
    resolution: str,
    *,
    as_of: date | None,
    model_variant: str | None,
) -> tuple[float, str, Mapping[str, Any], str]:
    key = _pricing_endpoint_key(endpoint, resolved_task)
    variant = _pricing_model_variant(endpoint, resolved_task, model_variant)
    config = H3_PRICING_REGISTRY[variant][key]
    pricing_type = str(config["pricing_type"])
    rates = config["rates"]
    promotion_end = config.get("promotion_end")
    effective_date = as_of or date.today()
    if pricing_type == "promotion" and promotion_end:
        end_date = date.fromisoformat(str(promotion_end))
        if effective_date > end_date:
            rates = config["standard_rate"]
            pricing_type = "standard_after_promotion"
    try:
        rate = float(rates[resolution])
    except KeyError as exc:
        raise FalValidationError(
            f"No H3 Max pricing is configured for {key} at {resolution!r}."
        ) from exc
    return rate, pricing_type, config, key


def _pricing_model_variant(
    endpoint: str | None, resolved_task: str, model_variant: str | None
) -> str:
    # Full endpoint identity is authoritative; never price Turbo as ordinary Max
    # just because both URLs end in image-to-video.
    variant = model_variant
    if endpoint:
        owner = next((
            name for name, model in H3_MODEL_REGISTRY.items()
            if endpoint in model["endpoints"].values()
        ), None)
        if owner is None or (variant is not None and variant != owner):
            raise FalValidationError("H3 pricing endpoint and model_variant do not match a published route.")
        variant = owner
    variant = variant if variant is not None else DEFAULT_MODEL_VARIANT
    task = {"t2va": "t2v", "i2va": "i2v", "fl2va": "fl2v", "l2va": "l2v", "ref2va": "ref2v"}.get(
        resolved_task, resolved_task
    )
    expected_endpoint = resolve_h3_endpoint(variant, task)
    if endpoint and endpoint != expected_endpoint:
        raise FalValidationError("H3 pricing endpoint does not match the requested task.")
    return variant


def estimate_h3_max_cost(
    *,
    resolved_task: str,
    endpoint: str | None = None,
    output_duration_seconds: float,
    resolution: str,
    reference_image_pixels: Sequence[int] = (),
    reference_video_seconds: Sequence[float] = (),
    reference_audio_seconds: Sequence[float] = (),
    as_of: date | None = None,
    model_variant: str | None = None,
) -> FalCostEstimate:
    """Estimate H3 Max billing using fal's published pricing formula."""
    output_rate, pricing_type, pricing, pricing_endpoint = _active_output_pricing(
        endpoint,
        resolved_task,
        resolution,
        as_of=as_of,
        model_variant=model_variant,
    )
    duration = float(output_duration_seconds)
    if not duration >= 0:
        raise FalValidationError("Output duration cannot be negative for cost estimation.")
    output_cost = duration * output_rate

    reference_tokens = 0.0
    reference_approximate = False
    if resolved_task in {"ref2va", "ref2v"}:
        reference = H3_MAX_PRICING["reference"]
        pixels_per_token = float(reference["image_pixels_per_token"])
        reference_tokens += sum(max(0, int(pixels)) / pixels_per_token for pixels in reference_image_pixels)

        video_rate = float(reference["video_tokens_per_second"][resolution])
        video_seconds = [max(0.0, float(value)) for value in reference_video_seconds]
        audio_seconds = [max(0.0, float(value)) for value in reference_audio_seconds]
        reference_tokens += sum(video_seconds) * video_rate
        reference_tokens += sum(audio_seconds) * float(reference["audio_tokens_per_second"])
        # fal documents video rates as rounded per-second values and audio as
        # "about" 80 tokens/s, so requests containing either remain estimates.
        reference_approximate = bool(video_seconds or audio_seconds)

    included = float(H3_MAX_PRICING["reference"]["included_tokens"])
    billable_tokens = max(0.0, reference_tokens - included)
    reference_cost = (
        billable_tokens
        * float(H3_MAX_PRICING["reference"]["usd_per_1000_tokens"])
        / 1000.0
    )
    # Promotional billing can be rounded in the fal dashboard and account-level
    # pricing may differ, so present a published promotional estimate with '~'.
    output_approximate = pricing_type == "promotion"
    approximate = output_approximate or reference_approximate
    return FalCostEstimate(
        output_video_cost=output_cost,
        reference_estimated_cost=reference_cost,
        estimated_total_cost=output_cost + reference_cost,
        reference_estimated_tokens=reference_tokens,
        reference_billable_tokens=billable_tokens,
        approximate=approximate,
        output_approximate=output_approximate,
        reference_approximate=reference_approximate,
        pricing_endpoint=pricing_endpoint,
        pricing_type=pricing_type,
        pricing_verified_on=str(pricing["verified_on"]),
        pricing_note=str(pricing["source_note"]),
        promotion_end=(str(pricing["promotion_end"]) if pricing.get("promotion_end") else None),
        pricing_model=str(h3_model_config(_pricing_model_variant(endpoint, resolved_task, model_variant))["model"]),
        price_per_second=output_rate,
    )


def format_h3_max_cost_report(estimate: FalCostEstimate, *, max_estimated_cost: float) -> str:
    # Keep existing Max report precision, while preserving Turbo's $0.03125.
    precision = max(4, len(str(estimate.price_per_second).partition(".")[2]))
    output_marker = "~" if estimate.output_approximate else ""
    reference_marker = "~" if estimate.reference_approximate else ""
    total_marker = "~" if estimate.approximate else ""
    reference_qualifier = " (approximate)" if estimate.reference_approximate else ""
    total_qualifier = " (approximate)" if estimate.approximate else ""
    lines = [
        "==============================",
        "COST",
        "==============================",
        "Estimated Cost:",
        f"output_video_cost: {output_marker}${estimate.output_video_cost:.{precision}f} USD",
        (
            "reference_estimated_cost: "
            f"{reference_marker}${estimate.reference_estimated_cost:.4f} USD{reference_qualifier}"
        ),
        f"estimated_total_cost: {total_marker}${estimate.estimated_total_cost:.{precision}f} USD{total_qualifier}",
        (
            "reference_estimated_tokens: "
            f"{reference_marker}{estimate.reference_estimated_tokens:.1f}"
        ),
        (
            "reference_billable_tokens: "
            f"{reference_marker}{estimate.reference_billable_tokens:.1f}"
        ),
        f"max_estimated_cost: ${max_estimated_cost:.4f} USD",
        f"pricing_endpoint: {estimate.pricing_endpoint}",
        f"pricing_model: {estimate.pricing_model}",
        f"price_per_second: ${estimate.price_per_second:.{precision}f} USD",
        f"pricing_type: {estimate.pricing_type}",
        f"pricing_verified_on: {estimate.pricing_verified_on}",
        f"pricing_note: {estimate.pricing_note}",
    ]
    if estimate.promotion_end:
        lines.append(f"promotion_end: {estimate.promotion_end}")
    if estimate.reference_estimated_tokens > 0:
        lines.append(
            "reference_billing_note: Ref2V reference inputs add token billing after the "
            "first 4096 reference tokens."
        )
    return "\n".join(lines)


def _slot_number(slot: str) -> int:
    try:
        return int(slot.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def _active_name(value: Any, input_directory: str | os.PathLike[str] | None) -> str | None:
    if value is None:
        return None
    name = str(value).strip()
    if not name or name == "(none)":
        return None
    if name.endswith(" [input]"):
        name = name[:-8]

    is_absolute = os.path.isabs(name) or PureWindowsPath(name).is_absolute()
    if is_absolute:
        if input_directory is None:
            raise ValueError("source_manifest media names must be relative to ComfyUI input")
        root = Path(input_directory).resolve()
        try:
            name = str(Path(name).resolve().relative_to(root))
        except ValueError as exc:
            raise ValueError("source_manifest media must be stored under ComfyUI input") from exc

    normalized = name.replace("\\", "/")
    if any(part == ".." for part in normalized.split("/")):
        raise ValueError("source_manifest media names cannot escape ComfyUI input")
    return normalized


def _is_active(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "(none)"}


def _trim_for_slot(gh_state_json: str, slot: str) -> tuple[float, float | None]:
    if not gh_state_json or gh_state_json == "(none)":
        return 0.0, None
    try:
        state = json.loads(gh_state_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0.0, None
    media = state.get("media", []) if isinstance(state, dict) else []
    try:
        entry = dict(media).get(slot)
    except (TypeError, ValueError):
        return 0.0, None
    if not isinstance(entry, dict) or entry.get("kind") != "audio":
        return 0.0, None
    try:
        start = max(0.0, float(entry.get("trimStart", 0) or 0))
        raw_end = entry.get("trimEnd")
        end = float(raw_end) if raw_end is not None else None
    except (TypeError, ValueError):
        return 0.0, None
    return start, end


def _muted_slots(gh_state_json: str) -> set[str]:
    if not gh_state_json or gh_state_json == "(none)":
        return set()
    try:
        state = json.loads(gh_state_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()
    media = state.get("media", []) if isinstance(state, dict) else []
    return {
        slot
        for slot, entry in media
        if isinstance(slot, str)
        and slot.startswith("ref_video_")
        and isinstance(entry, dict)
        and bool(entry.get("muted"))
    }


def resolve_source_task(main_mode: str, media_values: Mapping[str, Any]) -> str:
    """Resolve the provider-neutral visual task without changing local H3 semantics.

    Hybrid audio remains a separate manifest field. This intentionally keeps the
    version-1 task enum limited to the five task values requested by the manifest.
    """
    if main_mode == "text_keyframes":
        first = _is_active(media_values.get("first_frame"))
        last = _is_active(media_values.get("last_frame"))
        if first and last:
            return "fl2va"
        if first:
            return "i2va"
        if last:
            return "l2va"
        return "t2va"
    if main_mode == "all_reference":
        has_reference = any(
            _is_active(value)
            for slot, value in media_values.items()
            if slot.startswith(("ref_image_", "ref_video_", "ref_audio_"))
        )
        return "ref2va" if has_reference else "t2va"
    raise ValueError(f"Unknown MiniMax H3 main_mode: {main_mode}")


def build_source_manifest(
    *,
    input_prompt: str,
    conditioned_prompt: str,
    main_mode: str,
    aspect: str,
    width: int,
    height: int,
    requested_duration_seconds: float,
    local_frame_count: int,
    media_values: Mapping[str, Any],
    gh_state_json: str = "",
    input_directory: str | os.PathLike[str] | None = None,
    reference_video_audio_slots: set[str] | None = None,
) -> dict[str, Any]:
    """Build the small, provider-neutral source description consumed by cloud nodes."""
    resolved_task = resolve_source_task(main_mode, media_values)
    muted = _muted_slots(gh_state_json)
    reference_video_audio_slots = reference_video_audio_slots or set()

    def media_item(slot: str) -> dict[str, Any] | None:
        name = _active_name(media_values.get(slot), input_directory)
        return {"slot": slot, "name": name} if name else None

    if main_mode == "text_keyframes":
        first_frame = media_item("first_frame")
        last_frame = media_item("last_frame")
        hybrid_audio = media_item("hybrid_audio")
        if hybrid_audio is not None:
            trim_start, trim_end = _trim_for_slot(gh_state_json, "hybrid_audio")
            hybrid_audio.update({"trim_start": trim_start, "trim_end": trim_end})
        reference_images: list[dict[str, Any]] = []
        reference_videos: list[dict[str, Any]] = []
        reference_audios: list[dict[str, Any]] = []
    else:
        first_frame = last_frame = hybrid_audio = None
        reference_images = [
            item
            for slot in sorted(
                (key for key in media_values if key.startswith("ref_image_")),
                key=_slot_number,
            )
            if (item := media_item(slot)) is not None
        ]
        reference_videos = []
        for slot in sorted(
            (key for key in media_values if key.startswith("ref_video_")),
            key=_slot_number,
        ):
            item = media_item(slot)
            if item is not None:
                item["muted"] = slot in muted
                item["has_audio"] = slot in reference_video_audio_slots
                reference_videos.append(item)
        reference_audios = []
        for slot in sorted(
            (key for key in media_values if key.startswith("ref_audio_")),
            key=_slot_number,
        ):
            item = media_item(slot)
            if item is not None:
                trim_start, trim_end = _trim_for_slot(gh_state_json, slot)
                item.update({"trim_start": trim_start, "trim_end": trim_end})
                reference_audios.append(item)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "input_prompt": str(input_prompt or ""),
        "conditioned_prompt": str(conditioned_prompt or ""),
        "main_mode": main_mode,
        "resolved_task": resolved_task,
        "aspect": str(aspect),
        "target": {
            "width": int(width),
            "height": int(height),
            "requested_duration_seconds": float(requested_duration_seconds),
            "local_frame_count": int(local_frame_count),
            "local_duration_seconds": float(local_frame_count) / 24.0,
        },
        "first_frame": first_frame,
        "last_frame": last_frame,
        "reference_images": reference_images,
        "reference_videos": reference_videos,
        "reference_audios": reference_audios,
        "hybrid_audio": hybrid_audio,
    }
    validate_source_manifest(manifest)
    return manifest


def validate_source_manifest(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping):
        raise FalValidationError("MiniMax integration is missing a valid source_manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise FalValidationError(
            f"Unsupported source_manifest schema_version: {manifest.get('schema_version')!r}"
        )
    if manifest.get("main_mode") not in {"text_keyframes", "all_reference"}:
        raise FalValidationError("source_manifest main_mode is invalid")
    if manifest.get("resolved_task") not in SUPPORTED_TASKS:
        raise FalValidationError("source_manifest resolved_task is invalid")
    target = manifest.get("target")
    if not isinstance(target, Mapping):
        raise FalValidationError("source_manifest target is missing")
    for key in ("width", "height", "requested_duration_seconds", "local_frame_count"):
        if key not in target:
            raise FalValidationError(f"source_manifest target.{key} is missing")
    for key in ("reference_images", "reference_videos", "reference_audios"):
        if not isinstance(manifest.get(key), Sequence) or isinstance(manifest.get(key), (str, bytes)):
            raise FalValidationError(f"source_manifest {key} must be an array")


@dataclass(frozen=True)
class FalMediaUrls:
    first_frame: str | None = None
    last_frame: str | None = None
    reference_images: tuple[str, ...] = ()
    reference_videos: tuple[str, ...] = ()
    reference_audios: tuple[str, ...] = ()


@dataclass(frozen=True)
class FalPlan:
    model: str
    resolved_task: str
    endpoint: str
    prompt: str
    payload: dict[str, Any]
    report: str
    model_variant: str = DEFAULT_MODEL_VARIANT


@dataclass(frozen=True)
class FalGenerationResult:
    local_video_path: str | None
    video_url: str
    request_id: str
    endpoint: str
    report: str
    payload: dict[str, Any] = field(repr=False)
    expanded_prompt: str = ""
