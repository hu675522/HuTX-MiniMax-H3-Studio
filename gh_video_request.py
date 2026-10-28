from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from .fal_models import FalValidationError, validate_source_manifest
from .prompt_optimizer.config_schema import (
    OPTIMIZER_STATE_VERSION,
    assert_optimizer_persistence_safe,
    serialize_public_optimizer_config,
)


GH_VIDEO_REQUEST_SCHEMA_VERSION = 1
GH_VIDEO_REQUEST_KIND = "gh_video_request"
GH_PROMPT_TAG_SCHEME = "gh_media_v1"
LEGACY_PROMPT_TAG_SCHEME = "minimax_h3_local_v1"

CANONICAL_TASKS = {"t2v", "i2v", "l2v", "fl2v", "ref2v"}
MAIN_MODES = {"text_keyframes", "all_reference"}
CLOUD_ASPECTS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
LEGACY_TASK_MAP = {
    "t2va": "t2v",
    "i2va": "i2v",
    "l2va": "l2v",
    "fl2va": "fl2v",
    "ref2va": "ref2v",
}

_ANNOTATED_PATH_RE = re.compile(r"\s+\[(?:input|output|temp)\]\s*$", re.IGNORECASE)
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_REFERENCE_SLOT_RE = {
    "image": re.compile(r"^ref_image_([1-9])$"),
    "video": re.compile(r"^ref_video_([1-3])$"),
    "audio": re.compile(r"^ref_audio_([1-3])$"),
}
_FORBIDDEN_TOP_LEVEL_KEYS = {
    "conditioning",
    "latent",
    "model",
    "vae",
    "clip",
    "tensor",
    "width",
    "height",
    "frame_count",
    "local_frame_count",
    "local_duration_seconds",
    "endpoint",
    "payload",
}
_FORBIDDEN_REQUEST_KEY_MARKERS = _FORBIDDEN_TOP_LEVEL_KEYS | {
    "models",
    "model_variant",
    "fal_model",
    "fal_endpoint",
    "fal_payload",
    "local_width",
    "local_height",
    "local_latent_duration",
}
_SECRET_KEY_MARKERS = {
    "fal_key",
    "api_key",
    "api_keys",
    "authorization",
    "authorization_header",
    "cookie",
    "client_secret",
    "access_token",
    "refresh_token",
    "dashscope_key",
    "runninghub_key",
    "optimizer_credentials",
    "secret",
    "token",
    "credential_ref",
    "credential_refs",
}

@dataclass(frozen=True)
class NormalizedMediaEntry:
    slot: str
    name: str
    muted: bool = False
    trim_start: float = 0.0
    trim_end: float | None = None
    has_audio: bool | None = None


@dataclass(frozen=True)
class NormalizedVideoRequest:
    source_kind: str
    input_prompt: str
    routing_prompt: str
    prompt_tag_scheme: str
    main_mode: str
    resolved_task: str
    aspect: str
    duration_seconds: float
    first_frame: NormalizedMediaEntry | None
    last_frame: NormalizedMediaEntry | None
    reference_images: tuple[NormalizedMediaEntry, ...]
    reference_videos: tuple[NormalizedMediaEntry, ...]
    reference_audios: tuple[NormalizedMediaEntry, ...]
    hybrid_audio: NormalizedMediaEntry | None
    legacy_canvas: tuple[int, int] | None
    metadata: Mapping[str, Any]
    validation_notes: tuple[str, ...] = ()


def _key_is_secret(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in _SECRET_KEY_MARKERS or normalized.endswith("_api_key")


def _validate_request_field(location: tuple, key: str, value: Any, path: str) -> None:
    normalized_key = key.strip().lower().replace("-", "_")
    if normalized_key in _FORBIDDEN_REQUEST_KEY_MARKERS:
        raise FalValidationError(f"{path} must not contain local/backend field {key!r}.")


def _validate_cloud_state_field(location: tuple, key: str, value: Any, path: str) -> None:
    # Structural segments, not a dotted string: a key named 'optimizer.config'
    # or a nested metadata.optimizer.config must not acquire this exception.
    if location == ("optimizer", "config") and key == "model":
        if not isinstance(value, str):
            raise FalValidationError(f"{path}.model must be a string LLM model name.")
        return
    _validate_request_field(location, key, value, path)


def _validate_json_safe(
    value: Any,
    *,
    path: str = "request",
    _field_validator: Callable = _validate_request_field,
    _location: tuple = (),
) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FalValidationError(f"{path} contains a non-finite number.")
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise FalValidationError(f"{path} contains a non-string object key.")
            if _key_is_secret(key):
                raise FalValidationError(f"{path} must not contain secret field {key!r}.")
            _field_validator(_location, key, nested, path)
            _validate_json_safe(
                nested, path=f"{path}.{key}", _field_validator=_field_validator,
                _location=(*_location, key),
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _validate_json_safe(
                nested, path=f"{path}[{index}]", _field_validator=_field_validator,
                _location=(*_location, index),
            )
        return
    raise FalValidationError(
        f"{path} contains unsupported non-JSON value {type(value).__name__}; "
        "tensors and model objects are not allowed in GHVideoRequest."
    )


def migrate_cloud_state_json(state: Mapping[str, Any], *, notes: list[str] | None = None) -> dict[str, Any]:
    """Copy/migrate only the known v1 optimizer.config cache fields, before validation."""
    if not isinstance(state, Mapping):
        raise FalValidationError("gh_cloud_state_json must contain an object.")
    # Scan the original, including every discarded cache, so migration can never
    # conceal secrets, runtime objects, or invalid JSON values.
    assert_optimizer_persistence_safe(state, "gh_cloud_state_json")
    result = dict(state)
    if "optimizer" not in state:
        return result
    optimizer = state["optimizer"]
    if not isinstance(optimizer, Mapping):
        raise FalValidationError("gh_cloud_state_json.optimizer must be an object.")
    version = optimizer.get("optimizer_state_version", 1)
    if type(version) is not int or version not in {1, OPTIMIZER_STATE_VERSION}:
        raise FalValidationError("Unsupported optimizer_state_version.")
    migrated = dict(optimizer)
    if "config" in optimizer:
        migrated["config"] = serialize_public_optimizer_config(
            optimizer["config"], allow_derived=version == 1, notes=notes,
        )
    migrated["optimizer_state_version"] = OPTIMIZER_STATE_VERSION
    result["optimizer"] = migrated
    return result


def validate_cloud_state_json(state: Mapping[str, Any]) -> None:
    """UI-only migration and validation; the request validator never uses this policy."""
    state = migrate_cloud_state_json(state)
    _validate_json_safe(
        state, path="gh_cloud_state_json", _field_validator=_validate_cloud_state_field,
    )
    optimizer = state.get("optimizer", {})
    allowed = {"optimizer_state_version", "config", "original_prompt", "optimized_prompt", "optimizer_report", "report"}
    if set(optimizer) - allowed:
        raise FalValidationError("Invalid Cloud optimizer history/state fields.")
    if "original_prompt" in optimizer or "optimized_prompt" in optimizer:
        if any(not isinstance(optimizer.get(key), str) for key in ("original_prompt", "optimized_prompt")):
            raise FalValidationError("Prompt history before/after must both be strings.")
        pair = {key: optimizer[key] for key in ("original_prompt", "optimized_prompt")}
        if len(json.dumps(pair, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 262144:
            raise FalValidationError("Prompt history exceeds 256 KiB; no text was truncated.")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(nested) for key, nested in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(nested) for nested in value)
    return value


def validate_input_relative_name(value: Any) -> str:
    if not isinstance(value, str):
        raise FalValidationError("Cloud media name must be a ComfyUI input-relative string.")
    name = value.strip()
    if not name or "\x00" in name:
        raise FalValidationError("Cloud media name must not be empty.")
    if _ANNOTATED_PATH_RE.search(name):
        raise FalValidationError(
            f"Annotated media paths are not valid GHVideoRequest input names: {value!r}."
        )
    windows_path = PureWindowsPath(name)
    if windows_path.is_absolute() or windows_path.drive:
        raise FalValidationError(f"Cloud media path must be relative to ComfyUI input: {value!r}.")
    if PurePosixPath(name.replace("\\", "/")).is_absolute() or name.startswith(("\\\\", "//")):
        raise FalValidationError(f"Cloud media path must be relative to ComfyUI input: {value!r}.")
    if _URL_SCHEME_RE.match(name) or "://" in name:
        raise FalValidationError(f"Cloud media name must not be a URL: {value!r}.")
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise FalValidationError(
            f"Cloud media path contains an invalid or parent-traversal segment: {value!r}."
        )
    return "/".join(parts)


def _finite_float(value: Any, label: str, *, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FalValidationError(f"{label} must be a number.") from exc
    if not math.isfinite(result):
        raise FalValidationError(f"{label} must be finite.")
    if minimum is not None and result < minimum:
        raise FalValidationError(f"{label} must be at least {minimum:g}.")
    return result


def _media_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FalValidationError(f"{label} must be an object or null.")
    return value


def _plain_media(value: Any, *, expected_slot: str, label: str) -> NormalizedMediaEntry | None:
    if value is None:
        return None
    item = _media_mapping(value, label=label)
    allowed = {"slot", "name"}
    unknown = set(item) - allowed
    if unknown:
        raise FalValidationError(f"{label} contains unsupported fields: {sorted(unknown)!r}.")
    slot = str(item.get("slot") or "")
    if slot != expected_slot:
        raise FalValidationError(f"{label}.slot must be {expected_slot!r}.")
    return NormalizedMediaEntry(slot=slot, name=validate_input_relative_name(item.get("name")))


def _reference_media(
    value: Any,
    *,
    kind: str,
    label: str,
) -> tuple[NormalizedMediaEntry, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise FalValidationError(f"{label} must be an array.")
    result: list[NormalizedMediaEntry] = []
    seen_slots: set[str] = set()
    for index, raw_item in enumerate(value):
        item = _media_mapping(raw_item, label=f"{label}[{index}]")
        allowed = {"slot", "name"}
        if kind == "video":
            allowed.add("muted")
        if kind == "audio":
            allowed.update({"trim_start", "trim_end"})
        unknown = set(item) - allowed
        if unknown:
            raise FalValidationError(
                f"{label}[{index}] contains unsupported fields: {sorted(unknown)!r}."
            )
        slot = str(item.get("slot") or "")
        if not _REFERENCE_SLOT_RE[kind].fullmatch(slot):
            raise FalValidationError(f"{label}[{index}].slot is invalid: {slot!r}.")
        if slot in seen_slots:
            raise FalValidationError(f"{label} contains duplicate slot {slot!r}.")
        seen_slots.add(slot)
        name = validate_input_relative_name(item.get("name"))
        muted = False
        trim_start = 0.0
        trim_end = None
        if kind == "video":
            if "muted" in item and not isinstance(item["muted"], bool):
                raise FalValidationError(f"{label}[{index}].muted must be a boolean.")
            muted = bool(item.get("muted", False))
        if kind == "audio":
            trim_start = _finite_float(
                item.get("trim_start", 0.0), f"{label}[{index}].trim_start", minimum=0.0
            )
            raw_end = item.get("trim_end")
            trim_end = (
                _finite_float(raw_end, f"{label}[{index}].trim_end", minimum=0.0)
                if raw_end is not None
                else None
            )
            if trim_end is not None and trim_end <= trim_start:
                raise FalValidationError(
                    f"{label}[{index}].trim_end must be greater than trim_start."
                )
        result.append(
            NormalizedMediaEntry(
                slot=slot,
                name=name,
                muted=muted,
                trim_start=trim_start,
                trim_end=trim_end,
            )
        )
    return tuple(result)


def _hybrid_audio(value: Any) -> NormalizedMediaEntry | None:
    if value is None:
        return None
    item = _media_mapping(value, label="hybrid_audio")
    unknown = set(item) - {"slot", "name", "trim_start", "trim_end"}
    if unknown:
        raise FalValidationError(
            f"hybrid_audio contains unsupported fields: {sorted(unknown)!r}."
        )
    if item.get("slot") != "hybrid_audio":
        raise FalValidationError("hybrid_audio.slot must be 'hybrid_audio'.")
    trim_start = _finite_float(
        item.get("trim_start", 0.0), "hybrid_audio.trim_start", minimum=0.0
    )
    raw_end = item.get("trim_end")
    trim_end = (
        _finite_float(raw_end, "hybrid_audio.trim_end", minimum=0.0)
        if raw_end is not None
        else None
    )
    if trim_end is not None and trim_end <= trim_start:
        raise FalValidationError("hybrid_audio.trim_end must be greater than trim_start.")
    return NormalizedMediaEntry(
        slot="hybrid_audio",
        name=validate_input_relative_name(item.get("name")),
        trim_start=trim_start,
        trim_end=trim_end,
    )


def resolve_cloud_task(
    main_mode: str,
    *,
    first_frame: NormalizedMediaEntry | None,
    last_frame: NormalizedMediaEntry | None,
    reference_images: Sequence[NormalizedMediaEntry],
    reference_videos: Sequence[NormalizedMediaEntry],
    reference_audios: Sequence[NormalizedMediaEntry],
) -> tuple[str, tuple[str, ...]]:
    if main_mode == "text_keyframes":
        if first_frame is not None and last_frame is not None:
            return "fl2v", ()
        if first_frame is not None:
            return "i2v", ()
        if last_frame is not None:
            return "l2v", ()
        return "t2v", ()
    if main_mode == "all_reference":
        if reference_images or reference_videos or reference_audios:
            return "ref2v", ()
        return "t2v", ("all_reference_without_references_fallback_to_t2v",)
    raise FalValidationError(f"GHVideoRequest main_mode is invalid: {main_mode!r}.")


def validate_gh_video_request(request: Mapping[str, Any]) -> None:
    if not isinstance(request, Mapping):
        raise FalValidationError("GHVideoRequest must be an object.")
    _validate_json_safe(request, path="GHVideoRequest")
    unknown_forbidden = set(request).intersection(_FORBIDDEN_TOP_LEVEL_KEYS)
    if unknown_forbidden:
        raise FalValidationError(
            f"GHVideoRequest contains forbidden local/backend fields: {sorted(unknown_forbidden)!r}."
        )
    allowed = {
        "kind",
        "schema_version",
        "input_prompt",
        "prompt_tag_scheme",
        "main_mode",
        "resolved_task",
        "aspect",
        "duration_seconds",
        "first_frame",
        "last_frame",
        "reference_images",
        "reference_videos",
        "reference_audios",
        "hybrid_audio",
        "metadata",
    }
    unknown = set(request) - allowed
    if unknown:
        raise FalValidationError(f"GHVideoRequest contains unsupported fields: {sorted(unknown)!r}.")
    if request.get("kind") != GH_VIDEO_REQUEST_KIND:
        raise FalValidationError("GHVideoRequest kind must be 'gh_video_request'.")
    if request.get("schema_version") != GH_VIDEO_REQUEST_SCHEMA_VERSION:
        raise FalValidationError(
            f"Unsupported GHVideoRequest schema_version: {request.get('schema_version')!r}."
        )
    if not isinstance(request.get("input_prompt"), str):
        raise FalValidationError("GHVideoRequest input_prompt must be a string.")
    if request.get("prompt_tag_scheme") != GH_PROMPT_TAG_SCHEME:
        raise FalValidationError("GHVideoRequest prompt_tag_scheme must be 'gh_media_v1'.")
    if request.get("main_mode") not in MAIN_MODES:
        raise FalValidationError("GHVideoRequest main_mode is invalid.")
    if request.get("resolved_task") not in CANONICAL_TASKS:
        raise FalValidationError("GHVideoRequest resolved_task is invalid.")
    if request.get("aspect") not in CLOUD_ASPECTS:
        raise FalValidationError(f"GHVideoRequest aspect is invalid: {request.get('aspect')!r}.")
    _finite_float(request.get("duration_seconds"), "GHVideoRequest duration_seconds", minimum=0.001)
    metadata = request.get("metadata")
    if not isinstance(metadata, Mapping):
        raise FalValidationError("GHVideoRequest metadata must be an object.")


def normalize_cloud_request(request: Mapping[str, Any]) -> NormalizedVideoRequest:
    validate_gh_video_request(request)
    main_mode = str(request["main_mode"])
    first = _plain_media(request.get("first_frame"), expected_slot="first_frame", label="first_frame")
    last = _plain_media(request.get("last_frame"), expected_slot="last_frame", label="last_frame")
    images = _reference_media(request.get("reference_images"), kind="image", label="reference_images")
    videos = _reference_media(request.get("reference_videos"), kind="video", label="reference_videos")
    audios = _reference_media(request.get("reference_audios"), kind="audio", label="reference_audios")
    hybrid = _hybrid_audio(request.get("hybrid_audio"))

    if main_mode == "text_keyframes" and (images or videos or audios):
        raise FalValidationError(
            "GHVideoRequest text_keyframes mode must not contain active reference arrays."
        )
    if main_mode == "all_reference" and (first is not None or last is not None or hybrid is not None):
        raise FalValidationError(
            "GHVideoRequest all_reference mode must not contain keyframes or hybrid_audio."
        )
    derived_task, notes = resolve_cloud_task(
        main_mode,
        first_frame=first,
        last_frame=last,
        reference_images=images,
        reference_videos=videos,
        reference_audios=audios,
    )
    declared_task = str(request["resolved_task"])
    if declared_task != derived_task:
        raise FalValidationError(
            "GHVideoRequest resolved_task does not match active media: "
            f"declared {declared_task!r}, derived {derived_task!r}."
        )
    metadata = _freeze_json(request.get("metadata", {}))
    return NormalizedVideoRequest(
        source_kind="gh_cloud",
        input_prompt=str(request["input_prompt"]),
        routing_prompt=str(request["input_prompt"]),
        prompt_tag_scheme=GH_PROMPT_TAG_SCHEME,
        main_mode=main_mode,
        resolved_task=derived_task,
        aspect=str(request["aspect"]),
        duration_seconds=float(request["duration_seconds"]),
        first_frame=first,
        last_frame=last,
        reference_images=images,
        reference_videos=videos,
        reference_audios=audios,
        hybrid_audio=hybrid,
        legacy_canvas=None,
        metadata=metadata,
        validation_notes=notes,
    )


def _legacy_slot_number(entry: NormalizedMediaEntry) -> int:
    try:
        return int(entry.slot.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def _legacy_media(
    value: Any,
    *,
    label: str,
    muted: bool = False,
    trim: bool = False,
    has_audio: bool | None = None,
) -> NormalizedMediaEntry | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise FalValidationError(f"Legacy source_manifest {label} must be an object or null.")
    slot = str(value.get("slot") or "")
    name = validate_input_relative_name(value.get("name"))
    trim_start = _finite_float(value.get("trim_start", 0.0), f"{label}.trim_start", minimum=0.0) if trim else 0.0
    raw_end = value.get("trim_end") if trim else None
    trim_end = _finite_float(raw_end, f"{label}.trim_end", minimum=0.0) if raw_end is not None else None
    return NormalizedMediaEntry(
        slot=slot,
        name=name,
        muted=bool(value.get("muted", muted)),
        trim_start=trim_start,
        trim_end=trim_end,
        has_audio=(bool(value["has_audio"]) if "has_audio" in value else has_audio),
    )


def normalize_legacy_minimax(integration: Mapping[str, Any]) -> NormalizedVideoRequest:
    if not isinstance(integration, Mapping):
        raise FalValidationError("FalH3MaxVideoGH requires a MiniMax or GHVideoRequest object.")
    manifest = integration.get("source_manifest")
    if not isinstance(manifest, Mapping):
        raise FalValidationError(
            "This MiniMax integration object has no source_manifest. Re-run it with the V0.1 integration node."
        )
    validate_source_manifest(manifest)
    legacy_task = str(manifest["resolved_task"])
    try:
        canonical_task = LEGACY_TASK_MAP[legacy_task]
    except KeyError as exc:
        raise FalValidationError(f"Unsupported Legacy MiniMax task: {legacy_task!r}.") from exc
    target = manifest["target"]
    width = int(target["width"])
    height = int(target["height"])

    first = _legacy_media(manifest.get("first_frame"), label="first_frame")
    last = _legacy_media(manifest.get("last_frame"), label="last_frame")
    images = tuple(
        sorted(
            (
                _legacy_media(item, label="reference_images")
                for item in manifest.get("reference_images", [])
            ),
            key=lambda item: _legacy_slot_number(item),
        )
    )
    videos = tuple(
        sorted(
            (
                _legacy_media(item, label="reference_videos", muted=bool(item.get("muted", False)))
                for item in manifest.get("reference_videos", [])
            ),
            key=lambda item: _legacy_slot_number(item),
        )
    )
    audios = tuple(
        sorted(
            (
                _legacy_media(item, label="reference_audios", trim=True)
                for item in manifest.get("reference_audios", [])
            ),
            key=lambda item: _legacy_slot_number(item),
        )
    )
    hybrid = _legacy_media(manifest.get("hybrid_audio"), label="hybrid_audio", trim=True)
    return NormalizedVideoRequest(
        source_kind="legacy_minimax",
        input_prompt=str(manifest.get("input_prompt", "")),
        routing_prompt=str(manifest.get("conditioned_prompt", "")),
        prompt_tag_scheme=LEGACY_PROMPT_TAG_SCHEME,
        main_mode=str(manifest["main_mode"]),
        resolved_task=canonical_task,
        aspect=str(manifest.get("aspect", "adaptive")),
        duration_seconds=float(target["requested_duration_seconds"]),
        first_frame=first,
        last_frame=last,
        reference_images=tuple(item for item in images if item is not None),
        reference_videos=tuple(item for item in videos if item is not None),
        reference_audios=tuple(item for item in audios if item is not None),
        hybrid_audio=hybrid,
        legacy_canvas=(width, height),
        metadata=MappingProxyType(
            {
                "source_node": "MiniMaxH3IntegrationGH",
                "source_manifest_schema_version": int(manifest["schema_version"]),
                "legacy_resolved_task": legacy_task,
            }
        ),
    )


def normalize_video_request(value: Any) -> NormalizedVideoRequest:
    if isinstance(value, NormalizedVideoRequest):
        return value
    if not isinstance(value, Mapping):
        raise FalValidationError("FalH3MaxVideoGH requires a MiniMax or GHVideoRequest object.")
    if value.get("kind") == GH_VIDEO_REQUEST_KIND:
        return normalize_cloud_request(value)
    if "source_manifest" in value:
        return normalize_legacy_minimax(value)
    raise FalValidationError(
        "FalH3MaxVideoGH input is neither a Legacy MiniMax bundle nor a GHVideoRequest."
    )


def _state_media_map(state: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw_media = state.get("media", [])
    if not isinstance(raw_media, Sequence) or isinstance(raw_media, (str, bytes, bytearray)):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for item in raw_media:
        if (
            isinstance(item, Sequence)
            and not isinstance(item, (str, bytes, bytearray))
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], Mapping)
        ):
            result[item[0]] = item[1]
    return result


def build_cloud_video_request(
    *,
    main_mode: str,
    input_prompt: str,
    aspect: str,
    duration_seconds: float,
    media_values: Mapping[str, Any],
    gh_cloud_state_json: str = "",
) -> dict[str, Any]:
    state: Mapping[str, Any] = {}
    if gh_cloud_state_json and gh_cloud_state_json != "(none)":
        try:
            parsed = json.loads(gh_cloud_state_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FalValidationError("gh_cloud_state_json is not valid JSON.") from exc
        parsed = migrate_cloud_state_json(parsed)
        validate_cloud_state_json(parsed)
        state = parsed

    restored_mode = state.get("mode")
    if restored_mode in MAIN_MODES:
        main_mode = str(restored_mode)
    if isinstance(state.get("prompt"), str):
        input_prompt = str(state["prompt"])
    if state.get("aspect") in CLOUD_ASPECTS:
        aspect = str(state["aspect"])
    if state.get("duration_seconds") is not None:
        duration_seconds = _finite_float(
            state["duration_seconds"], "gh_cloud_state_json.duration_seconds", minimum=0.001
        )

    state_media = _state_media_map(state)
    state_media_is_authoritative = "media" in state

    def active_name(slot: str) -> str | None:
        entry = state_media.get(slot)
        if entry is not None:
            raw_name = entry.get("name")
            return validate_input_relative_name(raw_name) if raw_name else None
        if state_media_is_authoritative:
            return None
        raw_name = media_values.get(slot)
        if raw_name is None or str(raw_name).strip() in {"", "(none)"}:
            return None
        return validate_input_relative_name(raw_name)

    def plain(slot: str) -> dict[str, Any] | None:
        name = active_name(slot)
        return {"slot": slot, "name": name} if name else None

    def video(slot: str) -> dict[str, Any] | None:
        item = plain(slot)
        if item is None:
            return None
        entry = state_media.get(slot, {})
        item["muted"] = bool(entry.get("muted", False))
        return item

    def audio(slot: str) -> dict[str, Any] | None:
        item = plain(slot)
        if item is None:
            return None
        entry = state_media.get(slot, {})
        item["trim_start"] = _finite_float(
            entry.get("trim_start", 0.0), f"{slot}.trim_start", minimum=0.0
        )
        raw_end = entry.get("trim_end")
        item["trim_end"] = (
            _finite_float(raw_end, f"{slot}.trim_end", minimum=0.0)
            if raw_end is not None
            else None
        )
        return item

    if main_mode == "text_keyframes":
        first_frame = plain("first_frame")
        last_frame = plain("last_frame")
        hybrid_audio = audio("hybrid_audio")
        reference_images: list[dict[str, Any]] = []
        reference_videos: list[dict[str, Any]] = []
        reference_audios: list[dict[str, Any]] = []
    elif main_mode == "all_reference":
        first_frame = last_frame = hybrid_audio = None
        reference_images = [
            item
            for index in range(1, 10)
            if (item := plain(f"ref_image_{index}")) is not None
        ]
        reference_videos = [
            item
            for index in range(1, 4)
            if (item := video(f"ref_video_{index}")) is not None
        ]
        reference_audios = [
            item
            for index in range(1, 4)
            if (item := audio(f"ref_audio_{index}")) is not None
        ]
    else:
        raise FalValidationError(f"GHVideoRequest main_mode is invalid: {main_mode!r}.")

    normalized_first = _plain_media(first_frame, expected_slot="first_frame", label="first_frame")
    normalized_last = _plain_media(last_frame, expected_slot="last_frame", label="last_frame")
    normalized_images = _reference_media(reference_images, kind="image", label="reference_images")
    normalized_videos = _reference_media(reference_videos, kind="video", label="reference_videos")
    normalized_audios = _reference_media(reference_audios, kind="audio", label="reference_audios")
    resolved_task, _notes = resolve_cloud_task(
        main_mode,
        first_frame=normalized_first,
        last_frame=normalized_last,
        reference_images=normalized_images,
        reference_videos=normalized_videos,
        reference_audios=normalized_audios,
    )
    request = {
        "kind": GH_VIDEO_REQUEST_KIND,
        "schema_version": GH_VIDEO_REQUEST_SCHEMA_VERSION,
        "input_prompt": str(input_prompt or ""),
        "prompt_tag_scheme": GH_PROMPT_TAG_SCHEME,
        "main_mode": main_mode,
        "resolved_task": resolved_task,
        "aspect": str(aspect),
        "duration_seconds": float(duration_seconds),
        "first_frame": first_frame,
        "last_frame": last_frame,
        "reference_images": reference_images,
        "reference_videos": reference_videos,
        "reference_audios": reference_audios,
        "hybrid_audio": hybrid_audio,
        "metadata": {"source_node": "GHCloudVideoInputGH"},
    }
    validate_gh_video_request(request)
    return request
