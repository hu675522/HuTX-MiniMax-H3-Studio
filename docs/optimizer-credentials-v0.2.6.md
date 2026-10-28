# V0.2.6 · Prompt Optimizer Secure Credential Persistence

## Architecture and environment mapping

All online provider dispatch goes through `resolve_prompt_optimizer_api_key`:
provider environment → supplied valid SecretStore reference → provider DPAPI
credential → missing. An explicitly supplied expired or cross-provider reference
still fails closed when no environment override exists; it never silently falls
back to another key. `/secret`, opaque `credential_ref`, provider binding and the
existing eight-hour TTL remain. Manual/auto and Cloud/Local share this resolver.

| Provider | Fixed environment names, in order |
| --- | --- |
| dashscope | DASHSCOPE_API_KEY |
| openai | OPENAI_API_KEY |
| custom (OpenAI Compatible; API alias `openai-compatible`) | GH_PROMPT_OPTIMIZER_API_KEY |
| runninghub | RUNNINGHUB_API_KEY |
| runninghub_overseas | RUNNINGHUB_OVERSEAS_API_KEY, RUNNINGHUB_API_KEY |
| gemini | GEMINI_API_KEY, GOOGLE_API_KEY |
| openrouter | OPENROUTER_API_KEY |
| siliconflow | SILICONFLOW_API_KEY |

The existing RunningHub regional and Gemini aliases remain. The former global
`GH_PROMPT_OPTIMIZER_API_KEY` fallback now belongs only to Custom; it cannot be
automatically applied to unrelated providers. UI cannot select arbitrary env names.

## Persistence and API

Storage: `ComfyUI/user/default/HuTX-MiniMax-H3-Studio/prompt_optimizer_credentials/<provider>.dat`.
The manager reuses only the existing Windows DPAPI utility, not Fal credentials
or Fal state. Each JSON file contains version, provider ID, encrypted blob and
DPAPI/CurrentUser protection metadata. The encrypted envelope also binds the
provider; changing the outer filename/provider cannot transfer its key.
Writes use a temporary encrypted file and atomic replacement. No plaintext file.

`GET/POST/DELETE /api/hutx/minimax-h3/prompt-optimizer/credential`:

- GET selects provider by query, returning only provider, configured, active_source,
  environment_configured, session_configured, persisted_configured, persistence_supported.
- Session reference, if present, travels in `X-HuTX-Optimizer-Reference`, never in
  a URL or GET response. Responses use `Cache-Control: no-store`.
- POST accepts provider/api_key for DPAPI save. Session save continues using the
  compatibility `/api/goohai/minimax-h3/prompt-optimizer/secret` exchange.
- DELETE removes only the selected provider's persisted file; other providers,
  environment variables and session records remain.
- Corrupt/undecryptable credentials return the same status-only schema with HTTP
  409. The frontend displays “本机凭证不可用，请重新配置”. No automatic deletion.

Creation/import does not decrypt files, so a damaged file cannot prevent plugin
startup. Non-Windows systems support environment/session only; the UI explicitly
states persistence is unsupported and disables the local-save button.

## UX and lifecycle

Cloud and Local use the same panel showing active source and all three configured
states. Provider changes clear input, discard stale UI responses and refresh status.
The password field is never populated from storage; placeholder follows status.

“仅本次会话” performs the existing secret exchange. “安全保存到本机” performs the new
DPAPI POST. Both clear the input when the request is dispatched, show empty-input
errors and retain success/priority-warning feedback. “删除本机凭证” deletes only the
current provider, then refreshes the active source. In-flight actions are guarded
and buttons disabled. The existing settings Save still exchanges a newly entered
key as a session credential for compatibility.

After browser reload, JS references are lost; persisted credentials and environment
continue working without a fake reference. ComfyUI restart clears SecretStore;
the current Windows user can decrypt saved credentials. Local legacy-default
migration checks secure status before deciding whether OpenAI is unconfigured.

No status objects or credentials enter workflow/Cloud/Local state. The persistence
allowlist and optimize inline-key rejection remain. Provider errors retain stack
frames with redaction but omit provider-controlled error bodies, which might echo
key fragments or lengths. Successful provider output is also stripped of known
key/reference values. Fal credential files/resolver and all Fal code are unchanged.

## Validation

All external provider calls are mocked. Tests use isolated temporary credential
directories and synthetic keys, including actual Windows DPAPI round trips.
New tests cover eight online providers, restart-style reload, encrypted provider
binding, resolution combinations, targeted deletion, expired references, corrupt
ciphertext/wrong-user failure, unsupported OS, status-only API responses,
provider error redaction, shared UI events, input clearing, provider switching,
priority warnings, manual/auto optimize and secret-free workflow/report capture.
Existing Local state, TTL/reference security, Fal and routing tests remain enabled.
Final embedded-Python run: **491 passed in 12.34s**, including 29 new tests.

Changed files: `prompt_optimizer/credentials.py`, `config_schema.py`,
`provider_adapter.py`, `secrets.py`, `legacy.py`, `__init__.py` (all under
`prompt_optimizer/`); `web/js/prompt_optimizer_shared.js`,
`web/js/minimax_h3_integration.js`, `plugin_meta.py`, `README.md`, this document;
`tests/conftest.py`, `tests/frontend_optimizer_fixture.mjs`,
`tests/test_optimizer_secure_credentials.py`, `tests/test_optimizer_credential_runtime.py`,
`tests/test_optimizer_runtime_serialization.py`, `tests/test_plugin_identity.py`.
