# V0.3.1 · Local Studio Shared UX

## Architecture and persistence

`video_input_components.js` provides the existing Cloud styles and media cards through explicit data/callback parameters. `gh_video_input_shared.js` provides ratio, caret picker and prompt history. `prompt_optimizer_shared.js` owns provider UI, credentials, cancellation, timing, revision protection and the Queue hook. `responsive_dom_host.js` owns ComfyUI host sizing.

Cloud keeps its own controller/state → GHVideoRequest → Fal. Local uses `local_video_input_state.js` and `gh_local_video_input.js` → the unchanged Local graph builder → MODEL / MiniMax / local_report. No Cloud request object is constructed by Local.

The seven native widget values remain model_name, clip_name, video_vae_name, audio_vae_name, aspect, megapixels and duration_seconds. The custom controls read the real loader option lists and write those native values. No model object is stored in frontend state. The default expanded configuration panel can collapse into a filename/canvas/duration summary. Local canvas preview follows the existing 1024² MP area, independent nearest-32 rounding and 17n+5 frame rule.

`gh_local_state_json` and `node.properties.gh_local_video_state` store schema_version, mode, prompt, media, optional optimizer and optional ui.models_collapsed. The optimizer history stores the latest successful pair, public configuration and report only. Pair validation uses the same 256 KiB UTF-8 limit; the whole Local state retains its 1 MiB limit. User-authored prompt text is saved as entered and should not contain secrets the user does not intend to save.

`execution_state()` removes optimizer/history/UI fields before creating the legacy conditioning graph. History does not enter UNETLoader, conditioning metadata or the MiniMax bundle. The native model filename selections remain the only model configuration passed to the existing loaders.

## Local media semantics

| Mode | Canonical UI tags |
|---|---|
| T2VA | No active tags |
| I2VA | First frame → Picture 1 |
| L2VA | Last frame → Picture 1 |
| FL2VA | First → Picture 1; last → Picture 2 |
| Hybrid | Available keyframes in first/last order; hybrid audio → Audio 1; optimizer uses HYBRID template |
| Ref2VA | Picture and Video retain actual sparse slot ordinals; video soundtracks precede standalone audio in dense Audio order |

Examples: ref_image_3 stays `<Picture 3>`, ref_video_2 stays `<Video 2>`. The unchanged Local tokenizer packing step converts sparse ordinals to dense internal ordinals. This deliberately does not reuse Cloud's dense active-slot adapter. Duplicate filenames are display-only and cannot change identity. Deletion refreshes picker entries without rewriting existing prompt labels.

The read-only `/api/hutx/minimax-h3/local-media-info?name=...` endpoint validates input-relative paths and reads image dimensions or video stream metadata. It does not decode whole videos or load any model. Runtime metadata supplies reliable video-soundtrack ordering; audio picker entries wait until video metadata is known. Metadata is not persisted in workflow state. read_media=false does not create optimizer image snapshots; ordinary UI previews and canvas/track metadata remain available.

## Optimizer and history

The shared controller has explicit Local task/media/profile callbacks. Local AUTO resolves to Structured. Concise remains an explicit option; the old Local controller, which sends no tag_contract, retains its legacy Structured behavior. Cloud AUTO and its Ref2V recommendation are unchanged.

The existing `local_h3_v1` tag contract opts the new UI into shared opaque-placeholder protection with Local sparse labels. The backend rejects unknown/missing labels before the provider, and rejects dropped/invented labels afterwards. Existing credential APIs, provider binding, environment/session/DPAPI resolution and storage formats are unchanged. Local and Cloud use the same provider credentials.

Manual optimize never queues generation. Local Auto Optimize awaits validated results before calling the underlying ComfyUI queue method. Failure, cancellation or a stale revision throws a clear Queue-blocking error. No model load starts through that queue attempt. The same timer reports manual/automatic running, success, failure and cancellation. A failed or cancelled attempt retains the previous successful history pair. Restore/apply operates locally without another LLM call.

## Actual ComfyUI findings

The stale-width fixture reproduces `widget.width=444`, which causes the real overlay formula `(widget.width ?? node.width) - 2*margin` to produce a 424px host while the node is 720px wide. The existing responsive host binder clears that override and observes the actual `.dom-widget`; Local now uses it too.

A second actual-host issue was caught beyond the plain mock: ComfyUI's reactive DOMWidget value setter invokes its callback even when persistence writes a value. Local's original callback caused recursive persistence. A `persisting`/`restoring` guard now prevents callback reentry. Both a reactive-setter fixture and the real ComfyUI frontend passed after this fix.

| Node width | Host width | Root width |
|---:|---:|---:|
| 380 | 360 | 360 |
| 460 | 440 | 440 |
| 560 | 540 | 540 |
| 720 | 700 | 700 |
| 900 | 880 | 880 |

All rows passed for Local in both Edge mock and actual ComfyUI. Cloud/Fal legacy host fixtures passed the same widths. No horizontal overflow. Edge also verified caret top/middle/bottom, consecutive mentions, zoom, comparison views, history reconstruction and single failure/cancel badges. Actual ComfyUI verified the real loader lists (7 diffusion models, 3 text encoders and 3 VAEs), input preview and full browser reload history.

## Verification and scope

- Full pytest: **686 passed**, one pre-existing dependency warning about pynvml deprecation. **56 new cases** over V0.3.0's 630.
- Local mock controller: task/media maps, seven values, collapse, manual/auto profiles, read_media, shared secret exchange, cancellation, duplicate/revision guard, history across fresh JS processes, strict persistence and Queue→builder boundaries.
- Core file hashes unchanged: conditioning.py, prompt_tags.py, local_video_nodes.py, gh_video_request.py, cloud_video_nodes.py, fal_router.py, fal_upload.py, fal_api_client.py and fal_credentials.py. Existing legacy node-class AST regression passes.
- No real LLM/Fal calls, model downloads, new dependencies, commits or pushes.
- Isolated localhost:8190 real local smoke used V0.3.0 settings: FL2VA int8 checkpoint, existing 4-step LoRA, NVFP4 CLIP, FP16 video VAE, FP32 audio VAE, 0.5 MP, 16:9, requested 5 seconds, DynamicVRAM, seed 1. The UI Auto Optimize step used a mock provider.
- T2VA succeeded in **125.248s**; I2VA in **170.395s**. Both files have **960×544, 124 frames, 24fps, 5.1667s video and an audio stream**. L2VA/FL2VA/Ref2VA core was not changed or re-sampled; their existing contracts pass.

Obsolete v0.3.1 machine-readable test evidence and temporary development artifacts were removed during project cleanup.

Deploy to `D:\AI\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes\HuTX-MiniMax-H3-Studio`. Restart ComfyUI and hard-refresh the browser afterwards. The existing 8188 user process was not restarted by these tests.

## Changed release files

Production: local_media_info.py, local_video_state.py, nodes.py (route registration only), plugin_meta.py; web/js/gh_cloud_video_input.js, gh_local_video_input.js, gh_video_input_shared.js, local_video_input_state.js, prompt_optimizer_shared.js, video_input_components.js; prompt_optimizer/engine.py, legacy.py, profiles.py, template_manager.py; README.md.

Tests: browser_local_comfy_smoke.mjs, browser_local_shared_ux_fixture.mjs, browser_prompt_ux_preview.mjs, browser_responsive_host_fixture.mjs, frontend_local_video_fixture.mjs, frontend_optimizer_fixture.mjs, run_local_shared_smoke.py, run_local_smoke_server.py, test_cloud_frontend.py, test_local_shared_ux.py, test_local_video_frontend.py, test_plugin_identity.py. Documentation: this file and its JSON evidence.
