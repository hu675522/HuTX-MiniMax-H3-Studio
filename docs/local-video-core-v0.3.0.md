# V0.3.0 · Local Video Input Core

## Architecture audit

The old `MiniMaxH3IntegrationGH` produces one `MiniMax` bundle containing positive
conditioning, joint AV latent, mux audio, two VAEs, aligned dimensions/frame count,
conditioned prompt, media map, report, original-audio flag and the existing source
manifest. Its four existing Local classes are unchanged (AST fingerprints in tests).

Its internal loaders are ComfyUI `CLIPLoader.load_clip(name, "minimax")` and
`VAELoader.load_vae(name)` for both VAEs. The old main model is external:
`UNETLoader.load_unet(name, "default")` uses `comfy.sd.load_diffusion_model`.
LoRA operates on MODEL; Adapter's `models number` remains 0 for text/keyframes and
1 for references. Model Switch can continue using that selector.

Adapter outputs, unchanged:
`CONDITIONING, LATENT, VAE, VAE, INT, AUDIO, BOOLEAN, STRING, STRING, STRING`.
DualClock accepts MODEL + AV LATENT and produces MODEL + SAMPLER + SIGMAS.
BasicGuider/RandomNoise/SamplerCustomAdvanced perform sampling. AVDecode emits
frames, generated audio, video latent and audio latent. CreateVideo consumes
frames + audio + fps; SaveVideo consumes VIDEO. Use Adapter mux_audio when
`is_original_audio` is true, otherwise decoded generated audio.

## New boundary and wiring

Public node: `GHLocalVideoInputGH`, category `HuTX/MiniMax H3 Studio/Local`.
Outputs are **0 MODEL, 1 MiniMax integration, 2 STRING local_report**.
Seven native widgets lead the input list: model_name, clip_name, video_vae_name,
audio_vae_name, aspect, megapixels, duration_seconds. Lists come directly from
ComfyUI diffusion_models/text_encoders/vae search paths; no weight copying/download.

The node uses ComfyUI GraphBuilder expansion into an independent UNETLoader, the
unchanged old Local conditioning node and `GHLocalVideoInputOutputGH` (small
terminal utility checking the loaded MODEL family and assembling actual metrics).
There is no duplicated conditioning/sampling engine or Cloud request conversion.

Connect MODEL → optional LoRA → optional existing Model Switch → DualClock.
Connect integration → existing Adapter; its positive goes to BasicGuider and AV
latent to DualClock/Sampler. DualClock's MODEL goes to the guider, SAMPLER/SIGMAS
to SamplerCustomAdvanced. Feed sampled AV latent and Adapter VAEs to AVDecode.
This is an open graph: sampling, LoRA and decoding are not hidden inside input UI.

## Five modes and media

Text/keyframes resolves no images → T2VA; first only → I2VA; last only → L2VA;
both → FL2VA. All-reference explicitly requires at least one active reference.
Empty references raise an error instead of silently becoming T2VA. Inactive
uploads stay in the UI state but are omitted from the execution graph so stale
inactive files cannot be loaded accidentally.

Explicitly named official `minimax_h3_fl2va_*` / `minimax_h3_ref2va_*` checkpoint
families are checked against the selected task before graph expansion. A mismatch
requires the user to select the appropriate model; there is no silent model/mode
fallback. Third-party checkpoint capabilities are not inferred from arbitrary
names; their loaded MODEL must still be a MiniMax H3 model.

Reuse the old limits: 9 reference images, 3 reference videos, 3 standalone audios;
video soundtrack references remain paired with their video. Video mute and audio
trim controls retain old preprocessing semantics. Optional hybrid audio requires
a keyframe and delegates to the existing Hybrid path. No Fal reference/duration
limits are imported.

Local tags remain `prompt_tags.py`: stable slot ordinals are validated then packed
for the tokenizer. FL2VA retains the old `picture 1` / `picture 2` conversion;
L2VA's sole keyframe is Picture 1. Sparse Ref image/video slots retain their Local
ordinals before packing; video audio precedes standalone audio. There is no Fal
`the first frame` mapping and no new @ grammar.

Canvas calls the old calculate_canvas: MP is 1024² pixels, range 0.2–2.0, step 0.1,
32-pixel alignment. Adaptive follows the existing first active visual selection.
Duration retains 2–30 seconds in whole seconds, 24 fps, snapped upward to 17n+5.
For 5s / 0.5 MP / 16:9 this is **960×544, 124 frames, 5.166667s**.
Reports include requested aspect/MP/duration, actual dimensions/frame count/fps,
model selections and the existing conditioning report.

## State, caching and basic UI

Independent `gh_local_state_json` and `node.properties.gh_local_video_state` store
only schema_version=1, mode, prompt and validated media slot entries. Top model and
canvas widgets keep native ComfyUI serialization. Load/configure, deleted uploads
and node rebuild are covered by the actual JS panel fixture. Paths must remain
input-relative; unknown/runtime fields, duplicate slots and invalid trims fail.

Graph expansion keeps UNETLoader inputs stable across prompt edits, allowing
ComfyUI's existing graph cache to reuse it. Unchanged conditioning inputs can
reuse the entire old conditioning node. CLIP offloading and AVDecode cleanup keep
their old behavior; no new cache retains additional GPU model copies. As before,
changed prompts rerun the old conditioning executor and its CLIP/VAE loader calls.
DynamicVRAM/Low VRAM remain host settings, not fake new widgets.

The first UI uses native top controls, prompt and mode widgets plus a small media
upload panel. Shared upload/state integration points live in
`local_video_input_state.js`; mounting and native callbacks in
`gh_local_video_input.js`. Next-round shared visual components can attach there.
LLM configuration, @ picker, prompt history and complex responsive UI are excluded.

## Verification and reproduction

All pytest tests are offline/mock. The Local tests execute unchanged production
Local executor, Adapter, DualClock and Decode methods with loader/GPU stubs, plus
real graph construction, validation, tag mapping and frontend serialization.
Full regression retains Cloud/Fal schemas, credentials, endpoints and output order.

Opt-in scripts `tests/run_local_smoke_server.py` and `tests/local_smoke_workflow.py`
run a separate localhost:8190 instance with only this plugin, API nodes disabled,
offline model flags and outputs under `.local-smoke-v030`. The user's 8188 service
is not restarted. Inspect the workflow generator and choose existing filenames
before reuse. It runs real models only when launched explicitly, never via pytest.

Actual machine: ComfyUI 0.34.0, RTX 4070 12 GB, default DynamicVRAM.
Text/keyframe tests use the installed fl2va pruned int8 model, Qwen3-VL 32B NVFP4
CLIP, standard H3 video/audio VAEs and 4-step FL2V Turbo LoRA. Ref2VA uses the
installed ref2va pruned int8 model with the user's saved beta/res_multistep 20-step
configuration and no FL2V LoRA. Seed=1, 0.5 MP, 5 requested seconds throughout.
The obsolete v0.3.0 machine-readable smoke-test artifact was removed during project cleanup.
