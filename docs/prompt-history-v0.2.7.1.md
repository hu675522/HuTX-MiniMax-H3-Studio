# V0.2.7.1 Prompt History Persistence

## Audit and state

Cloud `state.prompt` is the editable current prompt. Previously, `createCloudPromptHistory`
held its own before/after closure, while the optimizer already serialized
`optimizer.original_prompt` / `optimizer.optimized_prompt`. `applyState()` called
`history.reset()` without hydrating those fields. `invalidate()` also erased the
optimizer pair when current text changed. Thus saving the current prompt did not
reliably preserve or reconstruct the history views.

The latest successful pair now reuses those existing string fields; no parallel
`prompt_history` object or new schema version is introduced:

```json
{
  "prompt": "Current editable text",
  "optimizer": {
    "optimizer_state_version": 2,
    "config": {"prompt_profile": "auto"},
    "original_prompt": "Before the latest successful optimization",
    "optimized_prompt": "Validated optimizer output",
    "optimizer_report": "Existing report string"
  }
}
```

## Lifecycle

Saved data is captured and history validated before view/controller construction.
Configure validates first, then hydrates the view and optimizer while persistence
notifications are suppressed. Existing widget serialization and
`node.properties.gh_cloud_video_state` store the same complete state.

Only a successful, validated optimize response commits both strings and changes
current text. Editing, restore and apply only change current text. Failed or
cancelled requests retain the pair. Edit/configure/removal invalidates pending
work; a revision check plus the existing abort/request guard rejects stale results,
including edit-then-edit-back. Manual and automatic optimization use one controller.
The execution widget exposes an optimized result only when it matches current text,
so history cannot override a manually restored/edited generation prompt.

Old states missing both fields show “暂无优化记录”; current text is never inferred
as a historical result. Existing nonempty legacy pairs can be hydrated directly.
Empty fields continue representing no successful record.

## Boundaries

Frontend and Python allow only the known optimizer state fields, and require both
history values to be strings. UTF-8 JSON for the pair is limited to 262144 bytes
(256 KiB), including field names and escaping. Oversized loads fail explicitly;
oversized results retain prior history/current text and show an error, without
truncation. No growing history array exists.

The UI pair is not copied into GHVideoRequest, NormalizedVideoRequest, Fal payload,
or optimizer report metadata. Existing global secret/model checks and config
allowlist remain in force. Structured credentials, headers, runtime, media bytes
and model objects are rejected. User-authored prompt text itself is serialized as
text and may contain private information; it is not a secret-detection service.

## Offline verification

`test_prompt_history_persistence.py` runs the actual Cloud panel, view, optimizer,
serializers, configure and removal hooks with a DOM shim and intercepted API calls.
It covers optimize → save → destroy → new node → load → readonly compare, a fresh
Node.js process simulating browser/process restart, restore/apply/edit, failures,
cancel, stale responses, duplicate requests, limits, malformed input and security.
Existing full regression tests cover canonical tags, profiles, output orders,
credentials and Fal routing. No real LLM/Fal request is made.
