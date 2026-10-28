import {videoInputStyles,createMediaCard} from "./video_input_components.js";
import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import {
    GH_CLOUD_AUDIO_SLOTS,
    GH_CLOUD_IMAGE_SLOTS,
    GH_CLOUD_MEDIA_SLOTS,
    GH_CLOUD_VIDEO_SLOTS,
    deriveCloudTask,
    findWidget,
    hideNativeWidget,
    inputMediaUrl,
    mediaKindForFile,
    mediaKindForSlot,
    parseCloudState,
    promptTagForSlot,
    uploadInputMedia,
    attachCloudMediaPicker,
    createCloudRatioSelector,
    createCloudPromptHistory,
} from "./gh_video_input_shared.js";
import { createPromptOptimizerController, validateCloudPromptHistory } from "./prompt_optimizer_shared.js";
import { bindResponsiveDomHost } from "./responsive_dom_host.js";
import {installStudioTheme as _installStudioTheme} from "./studio_theme.js";

const NODE = "GHCloudVideoInputGH";
const STATE_PROPERTY = "gh_cloud_video_state";
const STATE_WIDGET = "gh_cloud_state_json";
const WIDTH = 460;
const TEXT_SLOTS = ["first_frame", "last_frame", "hybrid_audio"];
const REFERENCE_IMAGE_SLOTS = GH_CLOUD_IMAGE_SLOTS.filter((slot) => slot.startsWith("ref_image_"));
const REFERENCE_AUDIO_SLOTS = GH_CLOUD_AUDIO_SLOTS.filter((slot) => slot.startsWith("ref_audio_"));

function isChinese() {
    const locale = String(app.extensionManager?.setting?.get?.("Comfy.Locale") || navigator.language || "");
    return locale.toLowerCase().startsWith("zh");
}

function label(english, chinese) {
    return isChinese() ? chinese : english;
}

function element(tag, className, text = "") {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text) item.textContent = text;
    return item;
}

function normalizedEntry(slot, raw = {}) {
    const kind = mediaKindForSlot(slot);
    const entry = {
        name: String(raw.name || ""),
        kind,
    };
    if (kind === "video") entry.muted = Boolean(raw.muted);
    if (kind === "audio") {
        const trimStart = Number(raw.trim_start ?? 0);
        const trimEnd = raw.trim_end == null || raw.trim_end === "" ? null : Number(raw.trim_end);
        entry.trim_start = Number.isFinite(trimStart) ? Math.max(0, trimStart) : 0;
        entry.trim_end = Number.isFinite(trimEnd) ? Math.max(0, trimEnd) : null;
    }
    return entry;
}

function createCloudPanel(node) {
    if (typeof node.addDOMWidget !== "function") return false;
    node.properties = node.properties || {};
    const stateWidget = findWidget(node, STATE_WIDGET);
    // Capture/validate saved data before constructing controllers or emitting state.
    const initial = node.properties?.[STATE_PROPERTY] || stateWidget?.value || "";
    const initialState = typeof initial === 'string' ? parseCloudState(initial) : initial;
    const initialHistory = validateCloudPromptHistory(initialState?.optimizer || {});
    for (const name of [
        "main_mode", "prompt", "aspect", "duration_seconds", ...GH_CLOUD_MEDIA_SLOTS, STATE_WIDGET,
        "optimizer_enabled", "optimized_prompt", "optimizer_report",
    ]) {
        hideNativeWidget(findWidget(node, name));
    }

    let mode = "text_keyframes";
    let promptValue = "";
    let aspect = "adaptive";
    let durationSeconds = 5;
    const media = new Map();
    let restoring = true;
    let optimizerController = null;

    const root = element("div", "gh-cloud-video-root");
    root.innerHTML = videoInputStyles;

    const header = element("div", "gh-cloud-head");
    const taskText = element("span", "gh-cloud-task");
    header.append(taskText, element("span", "gh-cloud-note", label("Pure cloud · no local conditioning", "纯云端 · 不执行本地 conditioning")));
    root.appendChild(header);

    const modes = element("div", "gh-cloud-modes");
    const textMode = element("button", "", label("Text / keyframes", "文本 / 首尾帧"));
    const referenceMode = element("button", "", label("All references", "全能参考"));
    modes.append(textMode, referenceMode);
    root.appendChild(modes);

    const controls = element("div", "gh-cloud-controls");
    const aspectField = element("div", "gh-cloud-field");
    aspectField.appendChild(element("span", "", label("Aspect", "画幅")));
    const ratio = createCloudRatioSelector({getTask:()=>deriveCloudTask(mode,media),getMode:()=>mode,label,onChange:persist});
    const aspectSelect = ratio.button;
    aspectField.appendChild(aspectSelect);
    const durationField = element("label", "gh-cloud-field");
    durationField.appendChild(element("span", "", label("Seconds", "秒数")));
    const durationInput = element("input");
    durationInput.type = "number";
    durationInput.min = "0.1";
    durationInput.max = "120";
    durationInput.step = "1";
    durationField.appendChild(durationInput);
    controls.append(aspectField, durationField);
    root.appendChild(controls);

    const prompt = element("textarea", "gh-cloud-prompt");
    prompt.placeholder = label("Describe the video. Type @ to insert media.", "描述视频；输入 @ 快捷引用素材。");
    const history = createCloudPromptHistory({textarea:prompt,label,initialState:initialHistory,onApply:value=>{
        mediaPicker.close();prompt.value=value;optimizerController?.invalidate();persist();
    }});
    root.appendChild(history.element);
    const mediaPicker = attachCloudMediaPicker({
        textarea: prompt, getMode: () => mode, getMedia: () => media, label,
        onChange: () => { optimizerController?.invalidate(); persist(); },
    });
    optimizerController = createPromptOptimizerController({
        api,
        app,
        node,
        label,
        inputMediaUrl,
        initialState: initialState?.optimizer || {},
        getPrompt: () => prompt.value,
        setPrompt: (value) => {
            history.record(optimizerController.stateForSerialization().original_prompt, String(value || ""));
            mediaPicker.close();
            prompt.value = String(value || "");
            promptValue = prompt.value;
            persist();
        },
        getTask: () => deriveCloudTask(mode, media),
        getDuration: () => durationSeconds,
        getMedia: () => media,
        onStateChange: () => {
            if (!restoring) persist();
        },
    });
    root.appendChild(optimizerController.element);
    const mediaRoot = element("div");
    root.appendChild(mediaRoot);

    function stateObject() {
        return {
            schema_version: 1,
            mode,
            prompt: promptValue,
            aspect,
            duration_seconds: durationSeconds,
            media: [...media.entries()].map(([slot, entry]) => [slot, { ...entry }]),
            optimizer: optimizerController?.stateForSerialization() || {},
        };
    }

    function syncWidgets() {
        const values = {
            main_mode: mode,
            prompt: promptValue,
            aspect,
            duration_seconds: durationSeconds,
            optimizer_enabled: optimizerController?.enabled() || false,
            optimized_prompt: optimizerController?.optimizedPrompt() || "",
            optimizer_report: optimizerController?.report() || "",
        };
        for (const [name, value] of Object.entries(values)) {
            const item = findWidget(node, name);
            if (item) item.value = value;
        }
        for (const slot of GH_CLOUD_MEDIA_SLOTS) {
            const item = findWidget(node, slot);
            if (item) item.value = media.get(slot)?.name || "";
        }
        const serialized = JSON.stringify(stateObject());
        if (stateWidget) stateWidget.value = serialized;
        node.properties[STATE_PROPERTY] = serialized;
    }

    function persist() {
        if (restoring) return;
        promptValue = prompt.value;
        aspect = aspectSelect.value;
        const parsedDuration = Number(durationInput.value);
        durationSeconds = Number.isFinite(parsedDuration) && parsedDuration > 0 ? parsedDuration : 5;
        syncWidgets();
    }

    function insertTag(tag) {
        if (!tag) return;
        const start = prompt.selectionStart ?? prompt.value.length;
        const end = prompt.selectionEnd ?? start;
        prompt.setRangeText(tag, start, end, "end");
        optimizerController?.invalidate();
        promptValue = prompt.value;
        persist();
        prompt.focus({ preventScroll: true });
    }

    async function chooseFile(slot, droppedFile = null) {
        const expectedKind = mediaKindForSlot(slot);
        const accept = {
            image: "image/*",
            video: "video/*,.mkv,.avi,.mov",
            audio: "audio/*,.flac,.m4a,.aac,.ogg,.opus",
        }[expectedKind];
        let file = droppedFile;
        if (!file) {
            file = await new Promise((resolve) => {
                const picker = document.createElement("input");
                picker.type = "file";
                picker.accept = accept;
                picker.onchange = () => resolve(picker.files?.[0] || null);
                picker.click();
            });
        }
        if (!file) return;
        if (mediaKindForFile(file) !== expectedKind) {
            alert(label(`Expected ${expectedKind} media.`, `需要 ${expectedKind} 类型素材。`));
            return;
        }
        try {
            const name = await uploadInputMedia(api, file);
            media.set(slot, normalizedEntry(slot, { name }));
            persist();
            render();
        } catch (error) {
            alert(error?.message || String(error));
        }
    }

    function mediaCard(slot) {
        return createMediaCard({slot,entry:media.get(slot),kind:mediaKindForSlot(slot),label,
            url:media.get(slot)?inputMediaUrl(api,media.get(slot).name):'',
            getTag:()=>promptTagForSlot(mode,slot,media),chooseFile,insertTag,
            removeMedia:()=>{media.delete(slot);persist();render();},onUpdate:persist});
    }
    function appendSection(title, slots, className = "") {
        const section = element("section", "gh-cloud-section");
        section.appendChild(element("div", "gh-cloud-section-title", title));
        const grid = element("div", `gh-cloud-grid ${className}`);
        for (const slot of slots) grid.appendChild(mediaCard(slot));
        section.appendChild(grid);
        mediaRoot.appendChild(section);
    }

    function render() {
        mediaPicker.refresh();
        ratio.refresh();
        textMode.classList.toggle("active", mode === "text_keyframes");
        referenceMode.classList.toggle("active", mode === "all_reference");
        taskText.textContent = `${deriveCloudTask(mode, media).toUpperCase()} · ${label("GHVideoRequest", "HuTX 云端请求")}`;
        mediaRoot.replaceChildren();
        if (mode === "text_keyframes") {
            appendSection(label("First / last frame and optional hybrid audio", "首帧 / 尾帧及可选 Hybrid 音频"), TEXT_SLOTS, "gh-cloud-keyframes");
            if (media.has("hybrid_audio")) {
                mediaRoot.appendChild(element("div", "gh-cloud-warning", label(
                    "H3 Max currently rejects hybrid audio with keyframes.",
                    "H3 Max 当前会明确拒绝首尾帧与 Hybrid 音频组合。",
                )));
            }
        } else {
            appendSection(label("Reference images", "参考图片"), REFERENCE_IMAGE_SLOTS);
            appendSection(label("Reference videos", "参考视频"), GH_CLOUD_VIDEO_SLOTS);
            appendSection(label("Reference audios", "参考音频"), REFERENCE_AUDIO_SLOTS);
            if (deriveCloudTask(mode, media) === "t2v") {
                mediaRoot.appendChild(element("div", "gh-cloud-empty-note", "all_reference_without_references_fallback_to_t2v"));
            }
        }
        node.setDirtyCanvas?.(true, true);
    }

    function applyState(rawState) {
        const state = typeof rawState === "string" ? parseCloudState(rawState) : (rawState || {});
        const restoredHistory = validateCloudPromptHistory(state.optimizer || {});
        restoring = true;
        if (["text_keyframes", "all_reference"].includes(state.mode)) mode = state.mode;
        promptValue = typeof state.prompt === "string" ? state.prompt : String(findWidget(node, "prompt")?.value || "");
        aspect = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"].includes(state.aspect)
            ? state.aspect
            : String(findWidget(node, "aspect")?.value || "adaptive");
        const restoredDuration = Number(state.duration_seconds ?? findWidget(node, "duration_seconds")?.value ?? 5);
        durationSeconds = Number.isFinite(restoredDuration) && restoredDuration > 0 ? restoredDuration : 5;
        media.clear();
        if (Array.isArray(state.media)) {
            for (const item of state.media) {
                if (!Array.isArray(item) || item.length !== 2 || !GH_CLOUD_MEDIA_SLOTS.includes(item[0])) continue;
                if (!item[1] || typeof item[1] !== "object" || !item[1].name) continue;
                media.set(item[0], normalizedEntry(item[0], item[1]));
            }
        } else {
            for (const slot of GH_CLOUD_MEDIA_SLOTS) {
                const name = String(findWidget(node, slot)?.value || "");
                if (name && name !== "(none)") media.set(slot, normalizedEntry(slot, { name }));
            }
        }
        prompt.value = promptValue;
        history.hydrate(restoredHistory);
        aspectSelect.value = aspect;
        durationInput.value = String(durationSeconds);
        optimizerController?.restore(state.optimizer || {});
        restoring = false;
        syncWidgets();
        render();
    }

    textMode.onclick = () => { mode = "text_keyframes"; persist(); render(); };
    referenceMode.onclick = () => { mode = "all_reference"; persist(); render(); };
    prompt.oninput = () => { promptValue = prompt.value; optimizerController?.invalidate(); persist(); };
    aspectSelect.onchange = persist;
    durationInput.onchange = persist;

    if (stateWidget) {
        stateWidget.serialize = true;
        stateWidget.options = stateWidget.options || {};
        stateWidget.options.serialize = true;
        stateWidget.serializeValue = () => { persist(); return stateWidget.value; };
    }

    const domWidget = node.addDOMWidget("gh_cloud_video_panel", "gh_cloud_video_panel", root, {
        serialize: false,
        hideOnZoom: false,
    });
    domWidget.options = domWidget.options || {};
    domWidget.options.serialize = false;
    domWidget.options.getMinHeight = () => 420;
    node.setSize([Math.max(380, node.size?.[0] || WIDTH), Math.max(620, node.size?.[1] || 0)]);
    const responsiveHost = bindResponsiveDomHost(node,domWidget,root,() => {
        mediaPicker.refresh();ratio.refresh();node.setDirtyCanvas?.(true,true);
    });

    const previousConfigure = node.onConfigure;
    node.onConfigure = function (info) {
        optimizerController?.cancel();
        const result = previousConfigure?.apply(this, arguments);
        requestAnimationFrame(() => {
            const saved = info?.properties?.[STATE_PROPERTY]
                || findWidget(this, STATE_WIDGET)?.value
                || this.properties?.[STATE_PROPERTY]
                || "";
            applyState(saved);
        });
        return result;
    };
    const previousSerialize = node.onSerialize;
    node.onSerialize = function () {
        persist();
        return previousSerialize?.apply(this, arguments);
    };
    const previousRemoved = node.onRemoved;
    node.onRemoved = function () {
        mediaPicker.destroy();
        ratio.destroy();responsiveHost.destroy();
        optimizerController?.destroy();
        return previousRemoved?.apply(this, arguments);
    };

    requestAnimationFrame(() => applyState(initial));
    return true;
}

app.registerExtension({
    name: "HuTX.MiniMaxH3Studio.CloudVideoInput",
    rh: { type: "nodes", nodes: [NODE] },
    async setup() {
        if (typeof app.ensureNodesRegistered === "function") {
            await app.ensureNodesRegistered(new Set([NODE]));
        }
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE) return;
        const previous = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = previous?.apply(this, arguments);
            if (!this._ghCloudVideoPanelReady && createCloudPanel(this)) {
                this._ghCloudVideoPanelReady = true;
            }
            return result;
        };
    },
});
