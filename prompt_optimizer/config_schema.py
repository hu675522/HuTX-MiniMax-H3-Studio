from __future__ import annotations

import os
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from ..fal_models import FalValidationError


OPTIMIZER_STATE_VERSION = 2
# Single source of truth. The matching JS schema block is generated from
# optimizer_persistence_schema(); a test checks exact equality on every run.
PERSISTED_OPTIMIZER_FIELDS = {
    **dict.fromkeys(("mode", "provider", "model", "base_url", "api_url", "protocol",
                     "output_language", "local_model", "local_mmproj", "local_device", "prompt_profile"), "string"),
    **dict.fromkeys(("read_media", "read_visual_media", "auto_optimize"), "boolean"),
    "max_tokens": "integer", "temperature": "number", "timeout": "number",
    # Local UI remembers the user's selected model for each provider, not a
    # fetched model catalogue. This map must survive save/reload.
    "provider_models": "string_map",
}
# Exact fields populated by get_prompt_optimizer_config / Local UI refreshes.
# Do not add speculative aliases: unknown fields remain fail-closed.
DERIVED_OPTIMIZER_FIELDS = {
    "models": "array", "mmproj_models": "array",
    "runninghub_models": "string_array", "runninghub_overseas_models": "string_array",
    "missing_dependencies": "string_array", "gguf_dependency": "object",
    "environment_api_key_providers": "string_array", "has_api_key": "boolean",
}
PERSISTENCE_SECRET_FIELDS = {
    "api_key", "api_keys", "authorization", "authorization_header", "cookie", "secret",
    "token", "client_secret", "access_token", "refresh_token", "fal_key",
    "dashscope_key", "runninghub_key", "optimizer_credentials", "credential_ref", "credential_refs",
}


def optimizer_persistence_schema() -> dict[str, Any]:
    return {"version": OPTIMIZER_STATE_VERSION, "fields": PERSISTED_OPTIMIZER_FIELDS,
            "derived": DERIVED_OPTIMIZER_FIELDS, "secrets": sorted(PERSISTENCE_SECRET_FIELDS)}


def render_optimizer_persistence_schema_js() -> str:
    return "const OPTIMIZER_PERSISTENCE_SCHEMA = " + json.dumps(
        optimizer_persistence_schema(), ensure_ascii=False, indent=4,
    ) + ";"


def assert_optimizer_persistence_safe(value: Any, path: str = "optimizer.config") -> None:
    """Scan before dropping any cache; never hide a secret inside migration."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise FalValidationError(f"{path} contains a non-string key.")
            normalized = key.strip().lower().replace("-", "_")
            if normalized in PERSISTENCE_SECRET_FIELDS or (
                normalized.endswith("_api_key") and normalized != "has_api_key"
            ):
                raise FalValidationError(f"{path} contains a forbidden secret field.")
            assert_optimizer_persistence_safe(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_optimizer_persistence_safe(item, f"{path}[{index}]")
        return
    raise FalValidationError(f"{path} contains a non-JSON or non-finite value.")


def _matches_persistence_type(value: Any, rule: str) -> bool:
    if rule == "string":
        return isinstance(value, str)
    if rule == "boolean":
        return isinstance(value, bool)
    if rule == "integer":
        return type(value) is int
    if rule == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if rule == "array":
        return isinstance(value, list)
    if rule == "string_array":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if rule == "object":
        return isinstance(value, Mapping)
    if rule == "string_map":
        return isinstance(value, Mapping) and all(isinstance(item, str) for item in value.values())
    return False


def serialize_public_optimizer_config(
    config: Mapping[str, Any], *, allow_derived: bool = True, notes: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise FalValidationError("optimizer.config must be an object.")
    assert_optimizer_persistence_safe(config)
    result = {}
    for key, value in config.items():
        rule = PERSISTED_OPTIMIZER_FIELDS.get(key)
        derived = key in DERIVED_OPTIMIZER_FIELDS
        if rule is None and allow_derived and derived:
            rule = DERIVED_OPTIMIZER_FIELDS[key]
        if rule is None:
            raise FalValidationError(f"optimizer.config.{key} is not a supported persisted optimizer setting.")
        if not _matches_persistence_type(value, rule):
            if key == "model":
                raise FalValidationError("optimizer.config.model must be a string LLM model name.")
            raise FalValidationError(f"optimizer.config.{key} must be a {rule.replace('_', ' ')}.")
        if key == "prompt_profile" and value not in {"auto", "concise", "structured"}:
            raise FalValidationError("optimizer.config.prompt_profile must be auto, concise, or structured.")
        if derived:
            if notes is not None:
                notes.append(f"dropped_legacy_optimizer_ui_field: {key}")
        else:
            result[key] = json.loads(json.dumps(value, ensure_ascii=False))
    return result


SECRET_FIELDS = frozenset(
    {"api_key", "api_keys", "authorization", "token", "credential_ref", "credential_refs"}
)
PROVIDER_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "runninghub": ("RUNNINGHUB_API_KEY",),
    "runninghub_overseas": ("RUNNINGHUB_OVERSEAS_API_KEY", "RUNNINGHUB_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "dashscope": ("DASHSCOPE_API_KEY",),
    "siliconflow": ("SILICONFLOW_API_KEY",),
    "custom": ("GH_PROMPT_OPTIMIZER_API_KEY",),
}


@dataclass(frozen=True)
class OptimizerConfigSummary:
    mode: str
    provider: str
    model: str
    max_tokens: int
    output_language: str
    read_media: bool
    auto_optimize: bool
    has_api_key: bool


def _environment_api_key(provider: str) -> str:
    names = PROVIDER_ENV_KEYS.get(provider, ())
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def configured_environment_providers() -> list[str]:
    return [provider for provider in PROVIDER_ENV_KEYS if _environment_api_key(provider)]


def normalize_optimizer_config(data: Mapping[str, Any] | None) -> dict[str, Any]:
    # Import lazily so the legacy implementation can call this module while it
    # is itself being initialized as part of the public package.
    from . import legacy

    raw = copy_optimizer_json(dict(data) if isinstance(data, Mapping) else {})
    # Legacy defaults contain empty key fields. Never carry even those fields
    # into the public request config; the route's inline-key guard runs first.
    raw.pop("api_key", None)
    raw.pop("api_keys", None)
    public = optimizer_request_config(raw)
    config = legacy._normalize_config(public)
    config.pop("api_key", None)
    config.pop("api_keys", None)
    if "prompt_profile" in public:
        config["prompt_profile"] = public["prompt_profile"]
    if public.get("credential_ref"):
        config["credential_ref"] = public["credential_ref"]
    return optimizer_request_config(config)


def copy_optimizer_json(value: Any) -> Any:
    """Copy plain JSON data without invoking runtime objects' copy/pickle hooks."""
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [copy_optimizer_json(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: copy_optimizer_json(item) for key, item in value.items()}
    raise ValueError("Optimizer data must contain only JSON-safe values; runtime objects are not allowed.")


def optimizer_request_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Public settings plus an opaque string reference, never a resolved key."""
    raw = copy_optimizer_json(dict(config))
    reference = raw.pop("credential_ref", "")
    if not isinstance(reference, str):
        raise ValueError("Optimizer credential_ref must be a string.")
    result = serialize_public_optimizer_config(raw)
    if reference.strip():
        result["credential_ref"] = reference.strip()
    return result


def public_optimizer_config(config: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in config.items() if key not in SECRET_FIELDS}
    result = serialize_public_optimizer_config(result)
    has_api_key = bool(config.get("api_key")) or str(config.get("provider") or "") in configured_environment_providers()
    result["api_key"] = ""
    result["api_keys"] = {}
    result.pop("credential_ref", None)
    result.pop("credential_refs", None)
    result["has_api_key"] = has_api_key
    result["environment_api_key_providers"] = configured_environment_providers()
    return result


def config_summary(config: Mapping[str, Any]) -> OptimizerConfigSummary:
    return OptimizerConfigSummary(
        mode=str(config.get("mode") or "api"),
        provider=str(config.get("provider") or ""),
        model=str(config.get("model") or ""),
        max_tokens=int(config.get("max_tokens") or 4096),
        output_language=str(config.get("output_language") or "English"),
        read_media=bool(config.get("read_media", True)),
        auto_optimize=bool(config.get("auto_optimize", False)),
        has_api_key=bool(config.get("api_key")),
    )
