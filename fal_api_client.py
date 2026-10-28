from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from .fal_credentials import resolve_fal_api_key, redact_fal_secrets, FalCredentialError, FalLogFilter
from .fal_upload import (
    FalUploadFilenameEncodingError, classify_upload_error, prepare_fal_upload_path,
    safe_upload_failure, safe_upload_logging,
)


class FalConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FalQueueResult:
    request_id: str
    result: Mapping[str, Any]


class FalApiClient:
    """Small lazy wrapper around the official fal-client package."""

    def __init__(self):
        try:
            key = resolve_fal_api_key()
        except FalCredentialError as exc:
            raise FalConfigurationError(str(exc)) from None
        try:
            sdk_logger = logging.getLogger("fal_client.client")
            if not any(isinstance(item, FalLogFilter) for item in sdk_logger.filters):
                sdk_logger.addFilter(FalLogFilter())
            sdk = importlib.import_module("fal_client")
            self._sdk = sdk.SyncClient(key=key)
        except ModuleNotFoundError as exc:
            if exc.name == "fal_client":
                raise FalConfigurationError("fal-client is not installed.") from None
            raise FalConfigurationError("Fal SDK initialization failed.") from None
        except Exception:
            raise FalConfigurationError("Fal SDK initialization failed.") from None

    def upload_file(self, path: str) -> str:
        with safe_upload_logging():
            try:
                with prepare_fal_upload_path(path) as upload_path:
                    return redact_fal_secrets(self._sdk.upload_file(
                        str(upload_path), repository="fal_v3", fallback_repository=[],
                    ))
            except Exception as exc:
                error_type, primary = classify_upload_error(exc)
                if error_type is not FalUploadFilenameEncodingError:
                    raise safe_upload_failure(exc) from None
            # Only filename encoding errors get one fresh staging/upload retry.
            # No model submission or obsolete fal/gcs repository is involved.
            try:
                with prepare_fal_upload_path(path, force=True) as upload_path:
                    return redact_fal_secrets(self._sdk.upload_file(
                        str(upload_path), repository="fal_v3", fallback_repository=[],
                    ))
            except Exception as exc:
                raise safe_upload_failure(exc, primary=primary) from None

    def submit_and_wait(
        self,
        endpoint: str,
        payload: Mapping[str, Any],
        *,
        on_submitted: Callable[[str], None] | None = None,
    ) -> FalQueueResult:
        try:
            handle = self._sdk.submit(endpoint, arguments=dict(payload))
            request_id = redact_fal_secrets(handle.request_id)
        except Exception as exc:
            raise RuntimeError("Fal submit failed: " + redact_fal_secrets(exc)) from None
        if on_submitted is not None:
            on_submitted(request_id)
        try:
            result = handle.get()
        except Exception as exc:
            raise RuntimeError(
                "fal request was submitted, but waiting for its result failed.\n"
                f"Request ID: {request_id}\n"
                "Use this Request ID to inspect/recover the request instead of submitting it again."
            ) from None
        if not isinstance(result, Mapping):
            raise RuntimeError(
                "fal H3 Max returned a non-object result.\n"
                f"Request ID: {request_id}"
            )
        def clean(value):
            if isinstance(value, str): return redact_fal_secrets(value)
            if isinstance(value, Mapping): return {redact_fal_secrets(k): clean(v) for k, v in value.items()}
            if isinstance(value, list): return [clean(v) for v in value]
            return value
        return FalQueueResult(request_id=request_id, result=clean(result))
