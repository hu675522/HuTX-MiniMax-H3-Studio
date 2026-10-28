from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence


def active_media_labels(media: Sequence[Mapping[str, Any]] | None) -> tuple[str, ...]:
    return tuple(
        str(item.get("label") or "").strip()
        for item in media or ()
        if str(item.get("label") or "").strip()
    )


def resolve_input_media(name: str) -> Path:
    """Resolve an input-relative filename through the existing safe analyzer path."""
    from . import legacy

    return legacy._resolve_input_file(name)


def list_visual_models() -> list[dict[str, Any]]:
    from . import legacy

    return legacy._scan_visual_models()

