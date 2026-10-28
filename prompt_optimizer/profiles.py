"""Cloud prompt strategies. Local retains its legacy Structured path."""
from __future__ import annotations

import re
from typing import Mapping

from .template_manager import CLOUD_TAG_CONTRACT, optimizer_task_name

PROMPT_PROFILES = ("auto", "concise", "structured")


def normalize_prompt_profile(value=None):
    profile = str(value or "auto").lower()
    if profile not in PROMPT_PROFILES:
        raise ValueError("prompt_profile must be auto, concise, or structured.")
    return profile


def resolve_prompt_profile(config: Mapping, payload: Mapping):
    if payload.get("tag_contract") == "local_h3_v1":
        requested = normalize_prompt_profile(config.get("prompt_profile"))
        return requested, "structured" if requested == "auto" else requested
    if payload.get("tag_contract") != CLOUD_TAG_CONTRACT:
        return "structured", "structured"
    requested = normalize_prompt_profile(config.get("prompt_profile"))
    task = optimizer_task_name(str(payload.get("task") or "t2v")).upper()
    if task not in {"T2VA", "I2VA", "FL2VA", "REF2VA"}:
        raise ValueError("Unsupported Cloud prompt profile task.")
    # Both H3 Max and Turbo share this mapping for their supported tasks.
    # Model capabilities (including unsupported Turbo Ref2V) remain Fal-owned.
    resolved = "structured" if task == "REF2VA" else "concise"
    return requested, resolved if requested == "auto" else requested


def concise_system_prompt(task, duration, labels, output_language, *, local=False):
    task = optimizer_task_name(task).upper()
    focus = {
        "T2VA": "Describe subject, action, scene, camera, lighting/style and critical constraints. Do not invent a media anchor.",
        "I2VA": "Begin from the supplied first-frame placeholder. Preserve identity, clothing, body proportions and important background. Describe required movement, plausible physics, camera motion and stability; do not inventory unrelated visual details.",
        "L2VA": "End at the supplied exact last-frame placeholder. Describe the preceding continuous motion towards that frame; preserve identity and scene continuity.",
        "HYBRID": "Preserve each supplied exact keyframe and audio placeholder, synchronizing visible action with the supplied audio. Do not invent replacement audio or reference identities.",
        "FL2VA": "Use both supplied frame placeholders: exact start-state, a continuous transition/action, and exact end-state. Preserve identity and scene continuity. Do not invent multiple shots unless the user explicitly requests cuts.",
        "REF2VA": "Use the supplied reference placeholders and retain their distinct identity, motion, scene and audio roles without conflating references.",
    }[task]
    return (
        ("You optimize a Local H3 video prompt using the CONCISE profile. Preserve concrete generation instructions. " if local else
         "You optimize a Cloud H3 video prompt using the CONCISE profile. This is an independent control-information pass, not a full screenplay rewrite. Let the video server perform its own expansion. ") +
        "Return only concise natural-language prompt prose in this logical order: media anchor, subject/action, "
        "preservation constraints, motion/physics, camera, critical constraints. "
        "Target 50–100 English words or approximately 100–220 Chinese characters; these are instruction targets, "
        "not truncation limits. Slightly exceed them when needed to preserve complex requirements. "
        "Do not add subject_definitions, summary, retention_analysis, detailed_description, "
        "integrated_multimodal_description, overall_soundscape or non_diegetic_music section headings. "
        "Do not invent sound or music unless explicitly requested by the original user prompt; when requested, "
        "preserve the sound/music constraint briefly in the prose. Preserve explicitly requested dialogue verbatim. "
        "Do not add analysis, scoring, preamble, code fences, or unrequested multi-shot scripts. "
        "Keep the user's event and important constraints; do not replace intent with generic cinematic decoration. "
        + focus + " "
        "Media bindings are opaque __GH_MEDIA_V1_*__ placeholders. Copy them byte-for-byte; preserve each supplied "
        "media identity and role. Keep every reference used by the user at least once. Meaningful repeated uses are "
        "allowed. Never translate, rename, omit, renumber, concatenate or invent a placeholder. Never emit numbered "
        "Picture, Image, Video or Audio labels directly; the application restores canonical tags afterwards. "
        f"Available placeholders: {', '.join(labels) or '(none)'}. "
        f"Duration: {duration:g} seconds. Output language: {output_language}."
    )


def validate_concise_output(text):
    # Do not truncate or disguise Structured output as Concise. A provider that
    # ignores the strategy gets a clear error without a second paid request.
    if re.search(r"(?im)^\s*(?:subject_definitions|summary|retention_analysis|detailed_description|integrated_multimodal_description|overall_soundscape|non_diegetic_music)\s*(?:[:：]|$)", text):
        raise ValueError("CONCISE profile returned Structured section headings; retry optimization.")
    return text.strip()
