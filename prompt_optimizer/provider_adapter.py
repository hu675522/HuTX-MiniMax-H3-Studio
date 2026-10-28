from __future__ import annotations

from typing import Any, Mapping

from .config_schema import optimizer_request_config
from .secrets import EPHEMERAL_SECRET_STORE, log_optimizer_exception, redact_secret_text
from .provider_errors import ProviderRequestError


def resolve_optimizer_api_key(config: Mapping[str, Any]) -> str:
    from .credentials import resolve_prompt_optimizer_api_key

    if config.get("mode") == "local":
        return ""
    provider = str(config.get("provider") or "").lower()
    reference = config.get("credential_ref")
    return resolve_prompt_optimizer_api_key(provider, reference)


async def request_optimized_prompt(
    config: Mapping[str, Any], payload: dict[str, Any], *, cancel_event=None
) -> str:
    """Dispatch through the existing, battle-tested provider implementations."""
    from . import legacy

    config = optimizer_request_config(config)
    api_key = ""
    try:
        api_key = resolve_optimizer_api_key(config)
        if config.get("mode") != "local" and not api_key:
            raise ValueError("请配置 API Key 或对应环境变量。")
        result = await legacy._request_async(config, payload, api_key=api_key, cancel_event=cancel_event)
        return redact_secret_text(result, (api_key, str(config.get("credential_ref") or "")))
    except Exception as error:
        sensitive = (api_key, str(config.get("credential_ref") or ""))
        if api_key:
            # Provider error bodies may echo prefixes/suffixes or lengths, not
            # just a full key. Retain frames, but never publish those bodies.
            log_optimizer_exception(error, sensitive, omit_detail=True)
            if type(error) is ProviderRequestError:
                raise RuntimeError(redact_secret_text(error, sensitive)) from None
            status = getattr(error, "status", None)
            suffix = f" (HTTP {status})" if type(status) is int and 100 <= status <= 599 else ""
            raise RuntimeError("LLM provider request failed; check provider configuration and credentials." + suffix) from None
        log_optimizer_exception(error, sensitive)
        raise RuntimeError(redact_secret_text(error, sensitive)) from None
