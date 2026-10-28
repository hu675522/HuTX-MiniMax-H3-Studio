from __future__ import annotations

import json
from typing import Any, Mapping

from .config_schema import config_summary, copy_optimizer_json, optimizer_request_config
from .media_analyzer import active_media_labels
from .provider_adapter import request_optimized_prompt
from .profiles import resolve_prompt_profile, validate_concise_output
from .template_manager import (
    CLOUD_TAG_CONTRACT,
    cloud_media_label_counts,
    optimizer_task_name,
    protect_cloud_input_prompt,
    protect_cloud_payload_bindings,
    restore_cloud_prompt,
)


async def optimize_payload(config: Mapping[str, Any], payload: dict[str, Any], *, cancel_event=None) -> str:
    """Common Local/Cloud optimizer engine; provider calls remain unchanged."""
    from . import legacy

    config = optimizer_request_config(config)
    request_payload = copy_optimizer_json(payload)
    _, resolved_profile = resolve_prompt_profile(config, request_payload)
    protection = None
    original_prompt = str(request_payload.get("prompt") or "")
    if request_payload.get("tag_contract") in {CLOUD_TAG_CONTRACT, "local_h3_v1"}:
        local = request_payload.get("tag_contract") == "local_h3_v1"
        protection = protect_cloud_input_prompt(
            original_prompt,
            "LOCAL" if local else str(request_payload.get("task") or "t2v"),
            request_payload.get("media") if isinstance(request_payload.get("media"), list) else [],
        )
        request_payload = protect_cloud_payload_bindings(request_payload, protection)
        request_payload["prompt"] = protection.protected_prompt
        context = dict(request_payload.get("context") or {})
        context["tag_contract"] = "local_h3_v1" if local else CLOUD_TAG_CONTRACT
        context["resolved_prompt_profile"] = resolved_profile
        request_payload["context"] = context

    result = await request_optimized_prompt(config, request_payload, cancel_event=cancel_event)
    if not result:
        raise RuntimeError("API 返回了空提示词")
    if protection is not None and resolved_profile == "concise":
        concise = validate_concise_output(legacy._strip_filenames(result))
        return restore_cloud_prompt(concise, protection)
    formatted = legacy._format_prompt_sections(legacy._strip_filenames(result))
    if protection is None:
        formatted = legacy._ensure_fl2va_picture_labels(
            formatted,
            str(request_payload.get("task") or "T2VA"),
            float(request_payload.get("duration") or 5),
            str(config.get("output_language") or "English"),
        )
    formatted = legacy._ensure_supplied_dialogues(
        formatted,
        original_prompt,
        str(config.get("output_language") or "English"),
    )
    formatted = legacy._normalize_subject_shorthand(formatted)
    if protection is not None:
        formatted = restore_cloud_prompt(formatted, protection)
    return formatted


def optimizer_report(
    *,
    config: Mapping[str, Any],
    payload: Mapping[str, Any],
    status: str,
    optimized_prompt: str | None = None,
    optimizer_elapsed_seconds: float | None = None,
) -> str:
    summary = config_summary(config)
    report = {
        "status": status,
        "task": optimizer_task_name(str(payload.get("task") or "t2v")),
        "provider": summary.provider,
        "model": summary.model,
        "mode": summary.mode,
        "max_tokens": summary.max_tokens,
        "output_language": summary.output_language,
        "read_media": summary.read_media,
        "media_labels": list(active_media_labels(payload.get("media") if isinstance(payload.get("media"), list) else [])),
        "tag_contract": str(payload.get("tag_contract") or "local_h3_v1"),
    }
    if report["tag_contract"] in {CLOUD_TAG_CONTRACT, "local_h3_v1"}:
        requested, resolved = resolve_prompt_profile(config, payload)
        report.update(requested_prompt_profile=requested, resolved_prompt_profile=resolved)
    if report["tag_contract"] == CLOUD_TAG_CONTRACT and optimized_prompt is not None:
        before = cloud_media_label_counts(str(payload.get("prompt") or ""), report["media_labels"])
        after = cloud_media_label_counts(optimized_prompt, report["media_labels"])
        report["media_label_counts_before"] = before
        report["media_label_counts_after"] = after
        report["media_label_multiplicity_changed"] = before != after
    if optimizer_elapsed_seconds is not None:
        report["optimizer_elapsed_seconds"] = max(0.0, float(optimizer_elapsed_seconds))
    return json.dumps(report, ensure_ascii=False, indent=2)
