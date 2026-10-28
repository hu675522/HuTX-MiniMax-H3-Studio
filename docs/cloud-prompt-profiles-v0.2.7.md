# V0.2.7 · Cloud Prompt Profiles

## Strategy

Only `auto`, `concise`, `structured` are supported. Profile is independent of LLM
provider/model, max_tokens, language, read_media and auto_optimize. Cloud uses AUTO
when an old workflow omits prompt_profile; the canonical optimizer configuration
allowlist persists an explicit selection. The generated JS schema matches Python.
GHVideoRequest and NormalizedVideoRequest are unchanged and do not carry profiles.

| Video model | T2V | I2V | FL2V | Ref2V |
| --- | --- | --- | --- | --- |
| H3 Max Turbo | Concise | Concise | Concise | Existing capability error |
| H3 Max | Concise | Concise | Concise | Structured |

AUTO depends on the resolved Cloud task because both model families share the
same recommendation for all supported tasks. No new Fal-node dependency or video
model input is added to Cloud. Changing model variant leaves the recommendation
valid for the supported task; the existing Fal capability guard rejects Turbo
Ref2V. Explicit Concise/Structured override AUTO. No Balanced profile.

## Independent Concise template

`prompt_optimizer/profiles.py` owns profile resolution and the Concise system
template. The engine adds a resolved strategy to its internal, JSON-only provider
context. The shared system dispatcher uses this template for all existing provider
transports, including RunningHub and Cloud-selected local LLMs. Read-media
attachments and provider transport options remain unchanged.

Concise asks for media anchor → subject/action → preservation constraints →
motion/physics → camera → critical constraints. It preserves identity, clothing,
proportions and important background for I2V; start/transition/end anchors for
FL2V; subject/action/scene/camera/lighting/style for T2V. It avoids unrelated visual
inventories, unrequested multi-shot scripts, and invented audio/music. Explicit
dialogue and audio/music constraints are retained briefly in prose.

Length instructions target 50–100 English words or approximately 100–220 Chinese
characters, allowing some extra detail for complexity. There is no substring
truncation. Concise skips the legacy section-building postprocessor. If a provider
returns Structured section headings, the output is rejected explicitly rather
than truncated or sent through an additional automatic LLM request.

The existing placeholder protection and restore validation remain the common
outer boundary. Required references, unknown-label rejection, media identity and
allowed repeated reference use are unchanged. Canonical tags reach the user.

## Structured and Local compatibility

Structured retains the mature system template and postprocessing, including the
six Ref2V sections: subject_definitions, summary, retention_analysis,
detailed_description, overall_soundscape, non_diegetic_music. Existing multiplicity
tests remain enabled. Local node payloads do not opt into Cloud profiles and keep
legacy Structured behavior even if a copied configuration contains prompt_profile.
Local frontend, credentials, DPAPI, SecretStore, TTL/reference, video routing,
pricing and Fal prompt_expansion_mode are unchanged.

## UI, history and reporting

Cloud configuration shows “提示词风格”: 自动推荐 / 精简 / 结构化. AUTO displays
“当前推荐：精简” or “当前推荐：结构化（Ref2V）”. The open dialog refreshes its recommendation
every 200 ms from the actual current task and clears the timer when closed.
Media-free all-reference mode still resolves to T2V under the existing contract.

Manual and automatic optimization use the same controller/config resolver. A
change of resolved profile permits re-optimization of the current optimized text;
the duplicate in-flight request guard remains. Existing Current/Original/Optimized/
Compare history and restore/apply controls continue to work.

Cloud optimizer_report adds `requested_prompt_profile` and `resolved_prompt_profile`
alongside existing timings. Example: `auto` → `concise`. Only ordinary profile
strings are persisted; runtime credential state is never added to workflow/state.

## Real A/B/C audit fixture

The original user-supplied Raw.txt, Concise.txt and Structured.txt were located in
the “比较H3 Max厂商性价比” task attachments. Their `input_prompt` sections were copied
without rewriting into [cloud_prompt_abc_audit.json](../tests/fixtures/cloud_prompt_abc_audit.json).
No report URLs, signed upload data, request identifiers or keys were copied.

| Audited prompt | User's subjective score |
| --- | --- |
| Raw | approximately 84/100 |
| Concise | approximately 93/100 |
| Structured | approximately 93/100 |

The supplied Structured audit measured approximately 11.18 s frontend optimization
and 9.24 s Fal-node elapsed, with server expansion set to balanced. The audit found
double expansion and no clear quality gain sufficient to justify default long
Structured output for Turbo I2V. This is design evidence from the user's audit,
not a new evaluation performed in this release, and not a runtime scoring rule.
Other AUTO mappings follow the requested first-release policy; no new quality or
latency claims are made for them. No live LLM/Fal calls were made in development.

## Changed files and verification

Runtime: `prompt_optimizer/profiles.py`, `config_schema.py`, `engine.py`, `legacy.py`;
`web/js/prompt_optimizer_shared.js`; `plugin_meta.py`.
Docs/fixtures: `README.md`, this file, `tests/fixtures/cloud_prompt_abc_audit.json`.
Tests: `tests/test_cloud_prompt_profiles.py`, `tests/frontend_optimizer_fixture.mjs`,
`tests/test_optimizer_persistence.py`, `tests/test_plugin_identity.py`.

49 new offline cases cover the supported-model AUTO matrix, overrides, independent
system instructions, I2V/FL2V/Ref2V tag boundaries, multimodal read on/off for all
HTTP protocols, RunningHub dispatch, no truncation, Structured and Local behavior,
route serialization and report fields, manual/auto UI, history, old workflow,
live task recommendation and real audit fixture provenance. Existing credential,
Fal routing, media multiplicity and request contract tests remain enabled.
Final embedded-Python run: **540 passed in 17.47s**. Seventeen protected
Fal/request/Local/credential/tag files matched the previous deployed release.
