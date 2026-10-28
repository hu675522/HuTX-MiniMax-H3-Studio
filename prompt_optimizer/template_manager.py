from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..prompt_tags import MEDIA_TAG_RE


CLOUD_TAG_CONTRACT = "gh_media_v1"
TASK_ALIASES = {
    "t2v": "T2VA",
    "t2va": "T2VA",
    "i2v": "I2VA",
    "i2va": "I2VA",
    "l2v": "L2VA",
    "l2va": "L2VA",
    "fl2v": "FL2VA",
    "fl2va": "FL2VA",
    "ref2v": "Ref2VA",
    "ref2va": "Ref2VA",
}
_CANONICAL_TAG_RE = re.compile(r"<\s*(Picture|Video|Audio)\s+(\d+)\s*>", re.IGNORECASE)
_PLACEHOLDER_LIKE_RE = re.compile(r"__GH[A-Z0-9_]*", re.IGNORECASE)


class OptimizerTagValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ProtectedCloudPrompt:
    original_prompt: str
    canonical_prompt: str
    protected_prompt: str
    task: str
    active_tags: tuple[str, ...]
    placeholders_by_tag: Mapping[str, str]
    expected_counts: Mapping[str, int]


def optimizer_task_name(resolved_task: str) -> str:
    return TASK_ALIASES.get(str(resolved_task or "").lower(), str(resolved_task or "T2VA"))


def _canonical_tag(media_type: str, ordinal: int) -> str:
    normalized = media_type.lower()
    label = "Picture" if normalized in {"image", "picture"} else normalized.title()
    return f"<{label} {ordinal}>"


def canonicalize_cloud_tags(text: str, resolved_task: str = "") -> str:
    del resolved_task  # gh_media_v1 is provider-neutral and task-independent.

    def replacement(match: re.Match[str]) -> str:
        media_type = str(match.group(1) or match.group(3))
        ordinal = int(match.group(2) or match.group(4))
        return _canonical_tag(media_type, ordinal)

    return MEDIA_TAG_RE.sub(replacement, str(text or ""))


def _active_cloud_tags(
    resolved_task: str, media: Sequence[Mapping[str, Any]] | None
) -> tuple[str, ...]:
    task = optimizer_task_name(resolved_task).upper()
    if task == "T2VA":
        return ()

    tags: list[str] = []
    for item in media or ():
        raw_label = str(item.get("label") or "").strip()
        if not raw_label:
            continue
        canonical = canonicalize_cloud_tags(raw_label)
        match = _CANONICAL_TAG_RE.fullmatch(canonical)
        if match is None:
            raise OptimizerTagValidationError(
                f"Invalid gh_media_v1 media label: {raw_label!r}."
            )
        tag = _canonical_tag(match.group(1), int(match.group(2)))
        if tag in tags:
            raise OptimizerTagValidationError(f"Duplicate active media label: {tag}.")
        tags.append(tag)

    if task == "I2VA" and tuple(tags) != ("<Picture 1>",):
        raise OptimizerTagValidationError("I2V active media must be exactly <Picture 1>.")
    if task == "FL2VA" and tuple(tags) != ("<Picture 1>", "<Picture 2>"):
        raise OptimizerTagValidationError(
            "FL2V active media must be exactly <Picture 1> and <Picture 2>."
        )
    if task == "REF2VA":
        for kind in ("Picture", "Video", "Audio"):
            ordinals = [
                int(_CANONICAL_TAG_RE.fullmatch(tag).group(2))
                for tag in tags
                if tag.startswith(f"<{kind} ")
            ]
            if ordinals != list(range(1, len(ordinals) + 1)):
                raise OptimizerTagValidationError(
                    f"Ref2V active {kind} labels must use dense ordinals starting at 1."
                )
    return tuple(tags)


def required_cloud_tags(
    resolved_task: str, media: Sequence[Mapping[str, Any]] | None = None
) -> tuple[str, ...]:
    """Compatibility name: returns active provider-neutral gh_media_v1 tags."""
    return _active_cloud_tags(resolved_task, media)


def _placeholder(tag: str) -> str:
    match = _CANONICAL_TAG_RE.fullmatch(tag)
    if match is None:
        raise OptimizerTagValidationError(f"Invalid canonical media tag: {tag!r}.")
    digest = hashlib.sha256(f"{CLOUD_TAG_CONTRACT}:{tag}".encode("utf-8")).hexdigest()[:12].upper()
    return f"__GH_MEDIA_V1_{match.group(1).upper()}_{match.group(2)}_{digest}__"


def protect_cloud_input_prompt(
    prompt: str,
    resolved_task: str,
    media: Sequence[Mapping[str, Any]] | None = None,
) -> ProtectedCloudPrompt:
    original = str(prompt or "")
    canonical = canonicalize_cloud_tags(original)
    active_tags = _active_cloud_tags(resolved_task, media)
    active_set = set(active_tags)

    prompt_tags = [
        _canonical_tag(match.group(1), int(match.group(2)))
        for match in _CANONICAL_TAG_RE.finditer(canonical)
    ]
    inactive = [tag for tag in prompt_tags if tag not in active_set]
    if inactive:
        raise OptimizerTagValidationError(
            "Prompt references inactive media labels: " + ", ".join(dict.fromkeys(inactive)) + "."
        )
    missing = [tag for tag in active_tags if tag not in prompt_tags]
    if missing:
        raise OptimizerTagValidationError(
            "Prompt must reference every active media label before optimization; missing: "
            + ", ".join(missing)
            + "."
        )

    placeholders = {tag: _placeholder(tag) for tag in active_tags}
    for placeholder in placeholders.values():
        if placeholder in canonical:
            raise OptimizerTagValidationError(
                "Prompt collides with a reserved gh_media_v1 optimizer placeholder."
            )
    expected_counts = {tag: prompt_tags.count(tag) for tag in active_tags}

    def replacement(match: re.Match[str]) -> str:
        tag = _canonical_tag(match.group(1), int(match.group(2)))
        return placeholders[tag]

    protected = _CANONICAL_TAG_RE.sub(replacement, canonical)
    return ProtectedCloudPrompt(
        original_prompt=original,
        canonical_prompt=canonical,
        protected_prompt=protected,
        task=optimizer_task_name(resolved_task),
        active_tags=active_tags,
        placeholders_by_tag=placeholders,
        expected_counts=expected_counts,
    )


def protect_cloud_payload_bindings(
    payload: Mapping[str, Any], protection: ProtectedCloudPrompt
) -> dict[str, Any]:
    """Replace provider-visible media labels without changing user-prompt counts."""
    result = copy.deepcopy(dict(payload))
    for item in result.get("media") or []:
        if not isinstance(item, dict) or not item.get("label"):
            continue
        tag = canonicalize_cloud_tags(str(item["label"]))
        item["label"] = protection.placeholders_by_tag.get(tag, tag)
    context = result.get("context")
    if isinstance(context, dict):
        for item in context.get("keyframes") or []:
            if not isinstance(item, dict) or not item.get("label"):
                continue
            tag = canonicalize_cloud_tags(str(item["label"]))
            item["label"] = protection.placeholders_by_tag.get(tag, tag)
    return result


def restore_cloud_prompt(
    optimized_prompt: str, protection: ProtectedCloudPrompt
) -> str:
    candidate = str(optimized_prompt or "")
    # Some providers render an existing binding as its visible media label
    # despite receiving an opaque token. Resolve only labels that were active
    # in this request; an invented number or media type must still fail.
    def restore_active_label(match: re.Match[str]) -> str:
        tag = _canonical_tag(match.group(1) or match.group(3), int(match.group(2) or match.group(4)))
        placeholder = protection.placeholders_by_tag.get(tag)
        if placeholder is None:
            raise OptimizerTagValidationError(
                f"Optimizer introduced an inactive media label: {tag}."
            )
        return placeholder

    candidate = MEDIA_TAG_RE.sub(restore_active_label, candidate)

    known_placeholders = set(protection.placeholders_by_tag.values())
    damaged_placeholders = [
        match.group(0) for match in _PLACEHOLDER_LIKE_RE.finditer(candidate)
        if match.group(0) not in known_placeholders
        or (match.start() > 0 and re.fullmatch(r"[A-Za-z0-9_]", candidate[match.start() - 1]))
    ]
    if damaged_placeholders:
        raise OptimizerTagValidationError(
            "Optimizer altered or invented a protected gh_media_v1 placeholder."
        )

    restored = candidate
    for tag, placeholder in protection.placeholders_by_tag.items():
        expected = int(protection.expected_counts.get(tag, 0))
        actual = candidate.count(placeholder)
        if expected > 0 and actual < 1:
            raise OptimizerTagValidationError(
                f"Optimizer damaged protected media label {tag}: expected at least 1, found {actual}."
            )
        restored = restored.replace(placeholder, tag)

    final_tags = {
        _canonical_tag(match.group(1) or match.group(3), int(match.group(2) or match.group(4)))
        for match in MEDIA_TAG_RE.finditer(restored)
    }
    required_tags = {tag for tag, count in protection.expected_counts.items() if count > 0}
    # Identity, not occurrence count or prose order, determines validity.
    # Keep these as separate sets even though current input validation requires
    # every active slot to be referenced in the source prompt.
    if not required_tags <= final_tags or not final_tags <= set(protection.active_tags):
        raise OptimizerTagValidationError(
            "Optimizer result does not preserve the original gh_media_v1 label contract."
        )
    return restored


def cloud_media_label_counts(text: str, active_tags: Sequence[str]) -> dict[str, int]:
    """Canonical counts for reports; never expose protected token spellings."""
    counts = {canonicalize_cloud_tags(tag): 0 for tag in active_tags}
    for match in _CANONICAL_TAG_RE.finditer(canonicalize_cloud_tags(text)):
        tag = _canonical_tag(match.group(1), int(match.group(2)))
        if tag in counts:
            counts[tag] += 1
    return counts


def enforce_cloud_tag_contract(
    optimized_prompt: str,
    resolved_task: str,
    protected_tags: ProtectedCloudPrompt,
) -> str:
    """Compatibility wrapper; strict restoration never appends guessed tags."""
    del resolved_task
    if not isinstance(protected_tags, ProtectedCloudPrompt):
        raise OptimizerTagValidationError("Cloud optimizer protection context is invalid.")
    return restore_cloud_prompt(optimized_prompt, protected_tags)
