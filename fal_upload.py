"""Local upload preparation and safe diagnostics; no CDN protocol or credentials."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from .fal_credentials import redact_fal_secrets


class FalUploadError(RuntimeError):
    pass


class FalUploadFilenameEncodingError(FalUploadError):
    pass


class FalUploadTransportError(FalUploadError):
    pass


class FalUploadProviderError(FalUploadError):
    pass


@contextmanager
def prepare_fal_upload_path(path: str | Path, *, force: bool = False):
    """Keep the original untouched; stage only an unsafe basename (or a retry)."""
    source = Path(path)
    if not force and source.name.isascii() and all(ord(c) >= 32 and ord(c) != 127 for c in source.name):
        yield source
        return
    # Media extensions are ASCII. Fail explicitly rather than silently changing
    # a non-ASCII extension or sending it back through an HTTP header.
    suffix = source.suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]+", suffix):
        raise FalUploadFilenameEncodingError("Fal upload filename has an unsupported extension.")
    digest = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:20]
    with tempfile.TemporaryDirectory(prefix="hutx_fal_") as directory:
        staged = Path(directory) / f"hutx_fal_{digest}{suffix}"
        shutil.copyfile(source, staged)
        yield staged


def upload_diagnostic(source: Path, upload_path: Path, *, kind: str, slot: str) -> dict:
    """Allowlisted metadata only: no original filename, path, headers or URLs."""
    mime = mimetypes.guess_type(upload_path)[0] or "application/octet-stream"
    return {
        "kind": kind if kind in {"first_frame", "last_frame", "reference_image", "reference_video", "reference_audio", "hybrid_audio"} else "media",
        "slot": slot if re.fullmatch(r"(?:first_frame|last_frame|hybrid_audio|ref_(?:image|video|audio)_[0-9]+)", slot) else "unspecified",
        "extension": source.suffix if re.fullmatch(r"\.[A-Za-z0-9]+", source.suffix) else "unsupported",
        "basename_contains_non_ascii": not source.name.isascii(),
        "upload_basename": upload_path.name if upload_path != source and re.fullmatch(r"hutx_fal_[0-9a-f]+\.[A-Za-z0-9]+", upload_path.name) else "(original or preprocessed ASCII basename)",
        "mime_type": mime,
    }


def classify_upload_error(exc: Exception) -> tuple[type[FalUploadError], str]:
    """Inspect the cause without publishing provider-controlled exception text."""
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, UnicodeEncodeError) or ("codec can't encode" in str(current).lower()):
            return FalUploadFilenameEncodingError, "fal_v3 filename encoding failure"
        current = current.__cause__ or current.__context__
    if isinstance(exc, OSError) or any(cls.__name__ in {"TransportError", "TimeoutException"} for cls in type(exc).__mro__):
        return FalUploadTransportError, "fal_v3 transport failure"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    detail = "fal_v3 provider failure"
    if isinstance(status, int) and 100 <= status <= 599:
        detail += f" (HTTP {status})"
    if "invalid storage type" in str(exc).lower():
        detail += " (unsupported storage type)"
    return FalUploadProviderError, detail


_LOG_LOCK = threading.Lock()
_ACTIVE_UPLOADS = 0


class _UploadLogFilter(logging.Filter):
    def filter(self, record):
        # Multipart SDK workers run in other threads. Process-wide activity also
        # covers their HTTP debug logs, which can include signed paths/tokens.
        if _ACTIVE_UPLOADS:
            record.msg = "Fal upload transport diagnostic (sensitive details omitted)."
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


@contextmanager
def safe_upload_logging():
    global _ACTIVE_UPLOADS
    with _LOG_LOCK:
        for name in ("fal_client.client", "httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
            logger = logging.getLogger(name)
            if not any(isinstance(item, _UploadLogFilter) for item in logger.filters):
                logger.addFilter(_UploadLogFilter())
        _ACTIVE_UPLOADS += 1
    try:
        yield
    finally:
        with _LOG_LOCK:
            _ACTIVE_UPLOADS -= 1


def safe_upload_failure(exc: Exception, *, primary: str | None = None) -> FalUploadError:
    error_type, detail = classify_upload_error(exc)
    message = f"Fal upload failed: primary: {primary}; retry: {detail}" if primary else f"Fal upload failed: primary: {detail}"
    return error_type(redact_fal_secrets(message))
