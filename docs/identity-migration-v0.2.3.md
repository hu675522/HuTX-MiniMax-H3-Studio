# HuTX · MiniMax H3 Studio — V0.2.3 migration

Development: `D:\PY\HuTX-MiniMax-H3-Studio`

Installation: `D:\AI\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes\HuTX-MiniMax-H3-Studio`

## Compatibility boundaries

Node IDs, input IDs, output positions, GHVideoRequest/NormalizedVideoRequest,
MiniMax bundle, `gh_*` state keys, tag schemes, optimizer state v2 and model_variant
are unchanged. Old workflow titles may remain user-visible until the user renames
them; never replace user-chosen titles automatically.

Category: `HuTX/MiniMax H3 Studio/{Cloud,Local,Utilities}`.

Registered frontend names: `HuTX.MiniMaxH3Studio.LocalStudio`,
`.CloudVideoInput`, `.FalVideo`, `.Timing`. Prompt Optimizer is a shared controller,
not a separately registered extension. No second optimizer hook is introduced.

The existing `/goohai/minimax-h3/prompt-optimizer/*` API remains the compatibility
route. Package `prompt_optimizer/` owns it; root `prompt_optimizer.py` is retained
legacy source and is not selected by normal Python package imports. Server-level
registration ownership prevents duplicate registrations through package aliases.

The old upload-cache basename is deliberately retained so changing display
identity does not trigger a new media upload. No key or processing parameters change.

## Safe deployment / rollback

1. Finish tests in the development tree. Stop ComfyUI before deployment.
2. Rename the development folder to the target above, preserving `.git` and all
   uncommitted files. Re-select that folder in your editor after the rename.
3. Copy source/web/locales/requirements to the new installation folder. Do not
   copy `.git`, test caches or Python bytecode. Do not overwrite an existing target.
4. Move the entire old installation to a unique subdirectory of
   `D:\AI\Plugin_Backup\`. This preserves its files and cache for recovery.
5. Ensure only the new identity is present in custom_nodes. Do not place backups
   anywhere underneath custom_nodes, even in a renamed backup folder.
6. Start ComfyUI normally, hard-refresh the browser, and open an old workflow.
   Do not Queue generate or auto-optimize during identity validation.
7. If rollback is needed, stop ComfyUI; move the new installation outside
   custom_nodes, then restore the old backup under its original name. Never load both.

## Static resources

`WEB_DIRECTORY = "./web"` lets ComfyUI register the actual directory name.
Sibling ESM imports and completion audio are relative to `import.meta.url`.
Host `/scripts/app.js` and `/scripts/api.js` remain host APIs, not plugin paths.
There is no legacy-folder static URL alias: hard-refresh/restart clears stale module
URLs; old workflow JSON contains node contracts, not extension module locations.

In browser Network, confirm HTTP 200 for `/extensions/HuTX-MiniMax-H3-Studio/js/`
entries: minimax_h3_integration.js, gh_cloud_video_input.js,
prompt_optimizer_shared.js, gh_video_input_shared.js, fal_h3_max_model_variant.js,
fal_h3_max_timing.js, fal_h3_max_timing_state.js, and `../audio/done.mp3`.

## Manual acceptance (no paid calls)

- Startup: no import/duplicate route error; node menu under HuTX.
- Local, Cloud, Fal Max/Turbo and optimizer panels render.
- Old workflow opens; default model remains H3 Max; output links remain attached.
- Optimizer disabled, execution_mode=dry_run: Turbo T2V and Max I2V pass.
- Save/reload: model/provider_models persist; catalogues, dependency/credential
  caches and secrets do not. Cloud/Fal outputs remain three/six, respectively.
- Automated local HTTP tests verify static-file resolution and 200 responses,
  but do not substitute for the user's real ComfyUI browser acceptance.
