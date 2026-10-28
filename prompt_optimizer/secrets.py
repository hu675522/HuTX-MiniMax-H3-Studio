from __future__ import annotations

import re
import logging
import traceback
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Iterable


DEFAULT_SECRET_TTL_SECONDS = 8 * 60 * 60
_AUTHORIZATION_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)([^\s,;]+)"
)
_QUERY_KEY_RE = re.compile(r"(?i)([?&](?:key|api_key)=)([^&\s]+)")


class OptimizerCredentialError(ValueError):
    """Credential errors intentionally contain no credential or reference value."""


@dataclass(frozen=True)
class _SecretRecord:
    provider: str
    api_key: str
    expires_at: float


class EphemeralSecretStore:
    """Process-memory-only optimizer credentials addressed by opaque references."""

    def __init__(self, ttl_seconds: float = DEFAULT_SECRET_TTL_SECONDS) -> None:
        self._ttl_seconds = float(ttl_seconds)
        self._records: dict[str, _SecretRecord] = {}
        self._lock = threading.RLock()

    def _purge_expired(self, now: float) -> None:
        expired = [ref for ref, record in self._records.items() if record.expires_at <= now]
        for ref in expired:
            self._records.pop(ref, None)

    def put(self, provider: str, api_key: str) -> str:
        normalized_provider = str(provider or "").strip().lower()
        normalized_key = str(api_key or "").strip()
        if not normalized_provider or not normalized_key:
            raise OptimizerCredentialError("Prompt optimizer provider and API key are required.")
        now = time.monotonic()
        reference = "ghopt_" + secrets.token_urlsafe(32)
        with self._lock:
            self._purge_expired(now)
            self._records[reference] = _SecretRecord(
                provider=normalized_provider,
                api_key=normalized_key,
                expires_at=now + self._ttl_seconds,
            )
        return reference

    def resolve(self, reference: str, provider: str) -> str:
        normalized_provider = str(provider or "").strip().lower()
        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            record = self._records.get(str(reference or ""))
        if record is None or record.provider != normalized_provider:
            raise OptimizerCredentialError(
                "Prompt optimizer session credential is missing or expired; enter the API key again."
            )
        return record.api_key

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(time.monotonic())
            return len(self._records)


EPHEMERAL_SECRET_STORE = EphemeralSecretStore()


def log_optimizer_exception(error: BaseException, secrets_to_redact: Iterable[str] = (), *, omit_detail: bool = False) -> None:
    # Never capture locals or attach exc_info: either would expose the raw key
    # to downstream handlers. Keep the original frames and line numbers.
    trace = traceback.TracebackException.from_exception(error, capture_locals=False)
    formatted = ("Traceback (most recent call last):\n" + "".join(trace.stack.format())
                 + "LLM provider request failed (sensitive response details omitted).\n") if omit_detail else "".join(trace.format(chain=False))
    safe_trace = redact_secret_text(formatted, secrets_to_redact)
    logging.getLogger(__name__).error("[HuTX H3 Studio] Prompt optimization failed:\n%s", safe_trace)


def redact_secret_text(value: object, secrets_to_redact: Iterable[str] = ()) -> str:
    """Return safe error/log text without known keys or common auth encodings."""
    text = str(value or "")
    for secret in sorted(
        {str(item) for item in secrets_to_redact if str(item)}, key=len, reverse=True
    ):
        text = text.replace(secret, "[REDACTED]")
    text = _AUTHORIZATION_RE.sub(r"\1[REDACTED]", text)
    return _QUERY_KEY_RE.sub(r"\1[REDACTED]", text)
