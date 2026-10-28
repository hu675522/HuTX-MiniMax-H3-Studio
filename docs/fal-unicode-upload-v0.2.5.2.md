# V0.2.5.2 · Fal Unicode Upload Reliability

## Evidence and scope

Actual embedded interpreter: `D:\AI\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe`.
`importlib.metadata.version("fal-client")` returned **1.0.1**. On 2026-09-06,
[PyPI](https://pypi.org/project/fal-client/) also lists 1.0.1 as latest (2026-08-19).
No SDK upgrade or package installation was performed.

The supplied traceback identifies `inspection.reference_images`, but neither the
original filename nor slot. It therefore cannot uniquely identify the historical
failed file. The input directory contains `参考图1.png` and `参考图2.png`; existence
alone does not prove which failed. No paid request was rerun to find out.

The installed SDK, without modifying `upload_file`, was exercised using
`httpx.MockTransport` and fake credentials. `中文文件名.png` reproducibly raises
`UnicodeEncodeError` with `encoding == "ascii"` and `object == source.name`, before
the upload transport is called. The exact source is:

1. `fal_client/client.py` `SyncClient.upload_file` passes `os.path.basename(path)`.
2. `SyncClient.upload` puts it directly in `X-Fal-File-Name` (line 2445).
3. `httpx/_models.py` `_normalize_header_value` executes
   `value.encode(encoding or "ascii")` (line 82).
4. The SDK default repositories are `fal_v3` then `fal` (lines 89–90).
5. `_try_upload_with_fallback` catches the encoding error and attempts `fal`.
   `_upload_via_storage` uses `storage_type=gcs` (line 1297). A mocked 400
   reproduces the final `Invalid storage type`, masking the first failure.

The auth-token call occurs while obtaining the CDN client, before the filename
header is built. A successful token response therefore does not guarantee that
the subsequent upload header can be encoded. Multipart creation uses the same
filename header (line 284) and is covered by a real SDK/mock transport test too.

## Upload flow

Original path/stat/transform → existing cache key → cache hit returns URL with no
staging or upload time; cache miss → existing preprocessing → ASCII staging if
needed → official `SyncClient.upload_file(repository="fal_v3", fallback_repository=[])`.

`prepare_fal_upload_path` uses the original path for ASCII basenames (including
spaces). Non-ASCII basenames get a temporary `hutx_fal_<hash>.ext` copy, preserving
extension case and bytes. `TemporaryDirectory` removes the copy on success and
failure. The original file is never moved, renamed or overwritten. The existing
cache version and identity (original absolute path, size, mtime_ns, transform)
are unchanged. A fresh process-style cache reload is also tested.

The API wrapper uses the same utility, so direct callers are protected as well.
Only a filename encoding failure gets one additional upload attempt with a fresh
ASCII staging path. Both attempts explicitly disable repository fallback. Other
errors propagate immediately. Generation submission remains outside this flow;
failure submits zero model requests, successful retry submits one.

Reference images/video/audio, first and last frames use the shared cache upload
path. The staging path also supports a `hybrid_audio` slot. The existing Fal
router rejects Hybrid audio plus keyframes because its model schema is unsupported;
this guard is deliberately unchanged, as are endpoints and canonical tag rules.

## Diagnostics and secret safety

Each cache-miss upload logs only kind, slot, extension, non-ASCII boolean, safe
staging basename (or a fixed ASCII-source marker), and MIME type. Failure repeats
that metadata at warning level, permitting exact slot identification on the next
failure without printing original paths or filenames.

Errors are classified as `FalUploadFilenameEncodingError`,
`FalUploadTransportError`, or `FalUploadProviderError`. Retry failure retains safe
`primary` and `retry` classifications, with numeric HTTP status when available.
Provider-controlled exception bodies/tracebacks are not forwarded; signed URLs,
tokens, headers and raw secrets cannot enter these messages. `redact_fal_secrets`
remains applied. SDK/httpx/httpcore diagnostics are replaced with a fixed safe
message while uploads are active, including multipart worker threads; existing
log levels remain. Outside uploads those diagnostics are unaffected.

No credential store, resolver, pricing, routing, request schema, prompt tags,
generation output order or download code changed. No real Fal/LLM requests.

## Tests

`tests/test_fal_unicode_upload.py` covers installed-SDK Unicode reproduction and
old fallback reproduction; ASCII/spaces, Chinese/Japanese/Korean/emoji files;
extension/content preservation; cleanup on both paths; v3 and multipart upload;
single encoding retry, classified retry failures and no transport retry;
source-based cache identity and zero-time cache hit without staging;
I2V/FL2V/Ref2V URLs and labels; hybrid slot staging; secret-free diagnostics;
failed upload never submits, and successful retry submits exactly once.
All HTTP uses MockTransport; socket connections are forbidden by the test fixture.

Validation on the actual embedded Python: **462 passed in 11.12s**, including
40 new parametrized Unicode upload cases. Existing credential, media-label
multiplicity, I2V/FL2V/Ref2V, cost guard and Fal routing regressions all pass.
The two existing SDK/cache mock signatures were updated for explicit repository
options and safe media diagnostics; their original assertions remain intact.

Changed release files: `fal_api_client.py`, `fal_media.py`, `fal_upload.py`,
`plugin_meta.py`, `README.md`, this audit, `tests/test_fal_unicode_upload.py`,
`tests/test_fal_credentials.py`, `tests/test_media_label_multiplicity.py`, and
`tests/test_plugin_identity.py`.
