from __future__ import annotations

import importlib


async def optimize_payload(config, payload, *, cancel_event=None):
    from .engine import optimize_payload as _optimize_payload

    return await _optimize_payload(config, payload, cancel_event=cancel_event)


def register_prompt_optimizer_routes():
    from .legacy import register_prompt_optimizer_routes as _register

    return _register()


def __getattr__(name: str):
    """Preserve imports of legacy helper names while the package is modularized."""
    if name in {
        "config_schema",
        "credentials",
        "engine",
        "legacy",
        "media_analyzer",
        "provider_adapter",
        "secrets",
        "template_manager",
    }:
        return importlib.import_module(f"{__name__}.{name}")
    legacy = importlib.import_module(f"{__name__}.legacy")
    try:
        return getattr(legacy, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

__all__ = ["optimize_payload", "register_prompt_optimizer_routes"]
