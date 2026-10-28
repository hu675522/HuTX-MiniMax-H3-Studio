const OPTIMIZER_ROUTE = "/goohai/minimax-h3/prompt-optimizer";

// BEGIN GENERATED PERSISTENCE SCHEMA (config_schema.py; do not edit by hand)
const OPTIMIZER_PERSISTENCE_SCHEMA = {
    "version": 2,
    "fields": {
        "mode": "string",
        "provider": "string",
        "model": "string",
        "base_url": "string",
        "api_url": "string",
        "protocol": "string",
        "output_language": "string",
        "local_model": "string",
        "local_mmproj": "string",
        "local_device": "string",
        "prompt_profile": "string",
        "read_media": "boolean",
        "read_visual_media": "boolean",
        "auto_optimize": "boolean",
        "max_tokens": "integer",
        "temperature": "number",
        "timeout": "number",
        "provider_models": "string_map"
    },
    "derived": {
        "models": "array",
        "mmproj_models": "array",
        "runninghub_models": "string_array",
        "runninghub_overseas_models": "string_array",
        "missing_dependencies": "string_array",
        "gguf_dependency": "object",
        "environment_api_key_providers": "string_array",
        "has_api_key": "boolean"
    },
    "secrets": [
        "access_token",
        "api_key",
        "api_keys",
        "authorization",
        "authorization_header",
        "client_secret",
        "cookie",
        "credential_ref",
        "credential_refs",
        "dashscope_key",
        "fal_key",
        "optimizer_credentials",
        "refresh_token",
        "runninghub_key",
        "secret",
        "token"
    ]
};
// END GENERATED PERSISTENCE SCHEMA
export const OPTIMIZER_STATE_VERSION = OPTIMIZER_PERSISTENCE_SCHEMA.version;

export const OPTIMIZER_PROVIDERS = {
    runninghub: { label: "RunningHub 国内版（推荐）", url: "https://www.runninghub.cn/openapi/v2", model: "openai/gpt-5.6-sol", protocol: "runninghub" },
    runninghub_overseas: { label: "RunningHub 海外版", url: "https://www.runninghub.ai/openapi/v2", model: "openai/gpt-5.6-sol", protocol: "runninghub" },
    openai: { label: "OpenAI", url: "https://api.openai.com/v1", model: "gpt-4.1-mini", protocol: "openai" },
    gemini: { label: "Google Gemini", url: "https://generativelanguage.googleapis.com/v1beta", model: "gemini-2.5-flash", protocol: "gemini" },
    openrouter: { label: "OpenRouter", url: "https://openrouter.ai/api/v1", model: "google/gemini-2.5-flash", protocol: "openai" },
    dashscope: { label: "阿里云百炼", url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen3-vl-plus", protocol: "openai" },
    siliconflow: { label: "SiliconFlow", url: "https://api.siliconflow.cn/v1", model: "Qwen/Qwen2.5-VL-72B-Instruct", protocol: "openai" },
    custom: { label: "Custom", url: "", model: "", protocol: "openai" },
};

// Only opaque server-session references live here. API keys are exchanged once
// through /secret and never enter node state, widget values, or /prompt data.
const credentialReferenceMemory = new Map();
const optimizerCredentialStatusMemory = new Map();
const OPTIMIZER_CREDENTIAL_ROUTE = "/hutx/minimax-h3/prompt-optimizer/credential";

export async function refreshOptimizerCredentialStatus(api, provider) {
    const reference = credentialReferenceMemory.get(provider);
    const response = await api.fetchApi(`${OPTIMIZER_CREDENTIAL_ROUTE}?provider=${encodeURIComponent(provider)}`, {
        cache: "no-store", headers: reference ? {"X-HuTX-Optimizer-Reference": reference} : {},
    });
    const data = JSON.parse(await response.text());
    if ((!response.ok && response.status !== 409) || typeof data.configured !== "boolean" || data.provider !== provider) throw new Error("凭证状态暂不可用");
    const status = {...data, unavailable: response.status === 409};
    optimizerCredentialStatusMemory.set(provider, status);
    return status;
}

export function createOptimizerCredentialPanel({api, provider, key, host, label = (en, zh) => zh, onChange}) {
    const panel = make("div", "gh-opt-secure-credentials");
    panel.style.cssText = "width:100%;min-width:0;box-sizing:border-box;display:grid;gap:6px;margin:8px 0;font-size:12px";
    const statusText = make("div", "gh-opt-secure-status"); statusText.style.whiteSpace = "pre-line";
    const buttons = make("div"); buttons.style.cssText = "display:flex;flex-wrap:wrap;gap:5px";
    const session = make("button", "", label("This session only", "仅本次会话"));
    const persist = make("button", "", label("Save securely on this computer", "安全保存到本机"));
    const remove = make("button", "", label("Delete local credential", "删除本机凭证"));
    const feedback = make("div", "gh-opt-credential-feedback"); feedback.style.whiteSpace = "pre-line";
    buttons.append(session, persist, remove); panel.append(statusText, buttons, feedback); host.append(panel);
    let busy = false, revision = 0, state = null;
    const message = (text, type = "info") => { feedback.textContent = text; feedback.dataset ? feedback.dataset.state = type : feedback.setAttribute("data-state", type); feedback.style.color = {success:"#71d998",error:"#ff8484",warning:"#ffd166",info:"#9fc0cc"}[type]; };
    const render = () => {
        if (!state) return;
        const source = {environment:"环境变量",session:"本次会话",persisted:"本机安全存储",none:"未配置"}[state.active_source];
        statusText.textContent = `当前生效：● ${source}\n环境变量：${state.environment_configured ? "✓ 已配置（优先级最高）" : "○ 未配置"}\n本次会话：${state.session_configured ? "✓ 会话已配置" : "○ 未配置"}\n本机凭证：${state.unavailable ? "本机凭证不可用，请重新配置" : state.persisted_configured ? "✓ Windows DPAPI 已保存" : "○ 未保存"}`;
        if (!state.persistence_supported) statusText.textContent += "\n当前系统暂不支持本机安全持久化。";
        key.placeholder = state.environment_configured ? "环境变量已配置，可输入其他凭证但当前不会优先生效" : state.session_configured ? "输入新的 API Key 以替换会话凭证" : state.persisted_configured ? "输入新的 API Key 以更新本机凭证" : "输入 API Key";
        session.disabled = busy; persist.disabled = busy || !state.persistence_supported;
        remove.disabled = busy || (!state.persisted_configured && !state.unavailable);
    };
    const refresh = async () => {
        const selected = provider.value, token = ++revision;
        state = null; statusText.textContent = "正在读取凭证状态…"; key.placeholder = "输入 API Key";
        try { const next = await refreshOptimizerCredentialStatus(api, selected); if (token !== revision || selected !== provider.value) return; state = next; render(); }
        catch { if (token === revision) statusText.textContent = optimizerCredentialStatus({provider:selected}, label); }
    };
    const action = async storage => {
        if (busy) return;
        const selected = provider.value;
        if (storage !== "delete" && !key.value.trim()) { message("✕ 请先输入 API Key", "error"); return; }
        if (storage === "delete" && state && !state.persisted_configured && !state.unavailable) { message("当前没有本机凭证可删除。"); return; }
        busy = true; provider.disabled = true; session.disabled = persist.disabled = remove.disabled = true;
        message(storage === "delete" ? "正在删除本机凭证…" : "● 正在安全保存…");
        try {
            let pending;
            if (storage === "session") pending = registerEphemeralOptimizerSecret(api, selected, key.value);
            else {
                const body = storage === "delete" ? undefined : new Blob([JSON.stringify({provider:selected,api_key:key.value.trim()})], {type:"application/json"});
                const reference = credentialReferenceMemory.get(selected);
                pending = fetchJson(api, `${OPTIMIZER_CREDENTIAL_ROUTE}?provider=${encodeURIComponent(selected)}`, {method:storage === "delete" ? "DELETE" : "POST",body,headers:reference ? {"X-HuTX-Optimizer-Reference":reference} : {}});
            }
            key.value = "";
            await pending;
            await refresh();
            onChange?.();
            if (storage === "delete") message("✓ 已删除当前平台的本机安全凭证", "success");
            else if (state?.environment_configured) message("⚠ 凭证已保存，但当前仍由环境变量生效", "warning");
            else if (storage === "persisted" && state?.session_configured) message("⚠ 本机凭证已保存，但当前仍由本次会话凭证生效", "warning");
            else message(storage === "session" ? "✓ 已保存到本次会话\nComfyUI 重启或会话 TTL 到期后失效" : "✓ 已使用 Windows DPAPI 安全保存到本机\nComfyUI 重启后仍可使用", "success");
        } catch { message("✕ 凭证操作失败，请检查平台及本机安全存储支持。", "error"); }
        finally { busy = false; provider.disabled = false; session.disabled = persist.disabled = remove.disabled = false; render(); }
    };
    session.onclick = () => action("session"); persist.onclick = () => action("persisted"); remove.onclick = () => action("delete");
    provider.addEventListener("change", () => {key.value = ""; message(""); refresh();});
    key.addEventListener("input", () => message(""));
    refresh();
    return {refresh, panel, action};
}

// Catalogue state is dialog-local; neither model lists nor credentials enter workflow JSON.
export function createApiModelSelector({api, provider, mode, model, readMedia, providerModels = {}, label = (en, zh) => zh}) {
    const root = make("div", "gh-opt-model-catalog");
    root.style.cssText = "display:grid;gap:6px;min-width:0;width:100%";
    const tools = make("div"); tools.style.cssText = "display:flex;gap:6px;min-width:0";
    const search = make("input", "gh-opt-model-search"); search.type = "search";
    search.placeholder = label("Search models", "搜索模型名称"); search.setAttribute("aria-label", search.placeholder);
    search.style.minWidth = "0";
    const refresh = make("button", "gh-opt-model-refresh", label("Refresh", "刷新")); refresh.type = "button";
    refresh.style.cssText = "flex:none;border:1px solid #8297aa;border-radius:8px;background:#40576b;color:#fff;padding:5px 9px;cursor:pointer";
    tools.append(search, refresh);
    const select = make("select", "gh-opt-model-select"); select.setAttribute("aria-label", label("API model", "API 模型"));
    const status = make("div", "gh-opt-model-status"); status.setAttribute("role", "status");
    status.style.cssText = "font-size:11px;line-height:1.5;overflow-wrap:anywhere";
    root.append(tools, select, model, status);
    let rows = null, source = "api", revision = 0, closed = false, abort = null, pending = null;
    const remembered = new Map(Object.entries(providerModels)); remembered.set(provider.value, model.value);
    let previous = provider.value;
    const message = (text, warning = false) => {status.textContent = text; status.style.color = warning ? "#ffe0a3" : "#d3e3ef";};
    const invalid = () => rows && (!rows.some(row => row.id === model.value) || (readMedia?.checked && rows.find(row => row.id === model.value)?.vision === false));
    const render = () => {
        const keyword = search.value.trim().toLowerCase();
        const visible = (rows || []).filter(row => row.id.toLowerCase().includes(keyword));
        select.replaceChildren();
        const chosen = rows?.find(row => row.id === model.value);
        // Keep the selection visible even when filtered or no longer in the catalogue.
        const placeholder = new Option(model.value ? `${model.value}${chosen ? "" : label(" (not listed)", "（不在列表中）")}` : label("Choose a model", "请选择模型"), model.value || "");
        select.append(placeholder);
        for (const row of visible) {
            if (row.id === model.value) continue;
            const option = new Option(row.id + (row.vision === false ? label(" (text only)", "（仅文本）") : ""), row.id);
            option.disabled = Boolean(readMedia?.checked && row.vision === false); select.append(option);
        }
        select.value = model.value;
        model.hidden = rows !== null; select.hidden = rows === null; search.hidden = rows === null;
        if (rows) {
            if (invalid()) message(label("Choose a listed model compatible with visual input.", "当前模型未列出或不支持视觉输入，请重新选择。"), true);
            else message(source === "application" ? label("Application model list; account access is not verified.", "已获取应用模型列表；不代表账户调用权限。") : label(`Fetched ${rows.length} models; quota and visual support depend on the provider.`, `已获取 ${rows.length} 个模型；调用权限、额度及视觉支持以平台为准。`));
        }
    };
    const load = () => {
        if (closed) return Promise.resolve();
        const token = ++revision, selected = provider.value;
        abort?.abort(); abort = new AbortController(); rows = null; render();
        const manual = mode.value === "local" || selected === "custom";
        tools.style.display = manual ? "none" : "flex"; refresh.disabled = false;
        if (manual) {message(label("Enter a model name manually.", "手动填写模型名称。")); pending = Promise.resolve(); return pending;}
        refresh.disabled = true; message(label("Fetching model list…", "正在获取当前 API 的模型列表…"));
        const reference = credentialReferenceMemory.get(selected);
        pending = (async () => {
            try {
                const data = await fetchJson(api, `/hutx/minimax-h3/prompt-optimizer/api-models?provider=${encodeURIComponent(selected)}`, {
                    cache:"no-store", signal:abort.signal, headers:reference ? {"X-HuTX-Optimizer-Reference":reference} : {},
                });
                if (closed || token !== revision || selected !== provider.value) return;
                rows = Array.isArray(data.models) ? data.models.filter(row => typeof row?.id === "string") : [];
                if (!rows.length) throw new Error(label("The provider returned an empty model list.", "平台返回的模型列表为空。"));
                source = data.source; render();
            } catch (error) {
                if (closed || token !== revision) return;
                rows = null; render();
                message((error?.message || label("Unable to fetch model list.", "无法获取模型列表。")) + label(" Current model kept; not verified. You can retry or enter it manually.", " 已保留当前模型（未验证），可刷新重试或手动填写。"), true);
            } finally {if (!closed && token === revision) refresh.disabled = false;}
        })();
        return pending;
    };
    select.onchange = () => {model.value = select.value; remembered.set(provider.value, model.value); render();};
    search.oninput = render;
    model.addEventListener("input", () => remembered.set(provider.value, model.value));
    readMedia?.addEventListener("change", render);
    refresh.onclick = load;
    return {root, refresh:load,
        providerChanged() {remembered.set(previous, model.value); previous = provider.value; model.value = remembered.get(previous) || OPTIMIZER_PROVIDERS[previous]?.model || ""; search.value = ""; return load();},
        async validate() {await pending; if (closed) throw new Error(label("Settings closed.", "设置已关闭。")); if (mode.value !== "local" && (!model.value.trim() || invalid())) throw new Error(label("Select a valid model from the API model list.", "请从 API 模型列表中选择有效模型；读取视觉素材时需要支持视觉输入的模型。"));},
        dispose() {closed = true; ++revision; abort?.abort();},
    };
}
const autoOptimizerHandlers = new Set();
let autoOptimizerQueueInstalled = false;

function clone(value) {
    if (!value || typeof value !== "object") return {};
    try { return structuredClone(value); }
    catch { return JSON.parse(JSON.stringify(value)); }
}

export function sanitizeOptimizerConfig(config) {
    let removedSecret = false;
    const sanitize = value => {
        if (Array.isArray(value)) return value.map(sanitize);
        if (!value || typeof value !== "object") return value;
        const result = {};
        for (const [key, item] of Object.entries(value)) {
            const normalized = key.trim().replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase().replaceAll("-", "_");
            if (OPTIMIZER_PERSISTENCE_SCHEMA.secrets.includes(normalized)
                || ["key", "bearer", "bearer_token", "raw_secret", "raw_api_key", "secret_ref"].includes(normalized)
                || normalized === "has_api_key" || normalized.endsWith("_api_key")) {
                if (!["credential_ref", "credential_refs", "has_api_key"].includes(normalized)
                    && item && (typeof item !== "object" || Object.keys(item).length)) removedSecret = true;
                continue;
            }
            result[key] = sanitize(item);
        }
        return result;
    };
    const result = sanitize(clone(config));
    if (removedSecret) console.error("[HuTX H3 Studio] Security error: secret removed from optimizer configuration; use environment or ephemeral secret exchange.");
    return result;
}

function validatePersistenceJson(value) {
    if (value == null || ["string", "boolean"].includes(typeof value)) return;
    if (typeof value === "number" && Number.isFinite(value)) return;
    if (Array.isArray(value)) { value.forEach(validatePersistenceJson); return; }
    if (typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
        Object.values(value).forEach(validatePersistenceJson); return;
    }
    throw new Error("Optimizer persistence contains a non-JSON value.");
}

export function serializePublicOptimizerConfig(config) {
    validatePersistenceJson(config);
    // Keep runtime credentials/catalogues available to the UI, but never save
    // them. Secret removal is an explicit security error, not normal migration.
    const safe = sanitizeOptimizerConfig(config);
    const result = {};
    const matches = (value, rule) => {
        if (rule === "string" || rule === "boolean") return typeof value === rule;
        if (rule === "integer") return Number.isInteger(value);
        if (rule === "number") return typeof value === "number" && Number.isFinite(value);
        if (rule === "array") return Array.isArray(value);
        if (rule === "string_array") return Array.isArray(value) && value.every(v => typeof v === "string");
        if (rule === "object" || rule === "string_map") return value !== null && typeof value === "object"
            && !Array.isArray(value) && (rule === "object" || Object.values(value).every(v => typeof v === "string"));
        return false;
    };
    for (const [key, value] of Object.entries(safe)) {
        const persistent = Object.hasOwn(OPTIMIZER_PERSISTENCE_SCHEMA.fields, key);
        const derived = Object.hasOwn(OPTIMIZER_PERSISTENCE_SCHEMA.derived, key);
        const rule = persistent ? OPTIMIZER_PERSISTENCE_SCHEMA.fields[key] : OPTIMIZER_PERSISTENCE_SCHEMA.derived[key];
        if ((!persistent && !derived) || !matches(value, rule)) {
            throw new Error(`Invalid persisted optimizer setting: ${key}`);
        }
        if (key === "prompt_profile" && !["auto", "concise", "structured"].includes(value)) throw new Error("Invalid prompt_profile.");
        if (persistent) result[key] = value;
    }
    return result;
}

export function rememberOptimizerCredentials(config) {
    if (!config || typeof config !== "object") return;
    for (const [provider, value] of Object.entries(config.credential_refs || {})) {
        if (value) credentialReferenceMemory.set(String(provider), String(value));
    }
    const provider = String(config.provider || "runninghub");
    if (config.credential_ref) credentialReferenceMemory.set(provider, String(config.credential_ref));
}

export function withMemoryOptimizerCredentials(config) {
    rememberOptimizerCredentials(config);
    const safe = sanitizeOptimizerConfig(config || {});
    const provider = String(safe.provider || "runninghub");
    const externallyConfigured = (Array.isArray(config?.environment_api_key_providers)
            && config.environment_api_key_providers.includes(provider));
    const credentialRef = credentialReferenceMemory.get(provider) || "";
    return {
        ...safe,
        credential_ref: credentialRef,
        has_api_key: Boolean(credentialRef || externallyConfigured || optimizerCredentialStatusMemory.get(provider)?.configured),
    };
}

export async function registerEphemeralOptimizerSecret(api, provider, apiKey) {
    let secret = String(apiKey || "").trim();
    if (!secret) return "";
    const body = new Blob([JSON.stringify({ provider: String(provider || ""), api_key: secret })], { type: "application/json" });
    secret = ""; apiKey = "";
    const data = await fetchJson(api, `${OPTIMIZER_ROUTE}/secret`, {
        method: "POST",
        body,
    });
    const credentialRef = String(data.credential_ref || "");
    if (!credentialRef) throw new Error("Prompt optimizer secret exchange returned no credential reference");
    credentialReferenceMemory.set(String(provider || "runninghub"), credentialRef);
    return credentialRef;
}

// UI runtime flags/catalogues must never be spread into an optimize request.
// In particular has_api_key matches the backend's *_api_key security guard.
export function resolveOptimizerCredential(config) {
    const runtime = withMemoryOptimizerCredentials(config);
    const requestConfig = serializePublicOptimizerConfig(runtime);
    if (requestConfig.mode !== "local" && runtime.credential_ref) {
        requestConfig.credential_ref = runtime.credential_ref;
    }
    return requestConfig;
}

export function optimizerCredentialStatus(config, label) {
    const runtime = withMemoryOptimizerCredentials(sanitizeOptimizerConfig(config));
    if (runtime.credential_ref) return label("Session credential configured", "会话已配置");
    if (runtime.has_api_key) return label("Environment variable configured", "环境变量已配置");
    return label("Not configured", "未配置");
}

export function optimizerCredentialError(error, config, label) {
    const message = error?.message || String(error);
    if (message.includes("session credential is missing or expired")) {
        const provider = String(config?.provider || "runninghub");
        // Do not erase a newer credential saved while this request was running.
        if (credentialReferenceMemory.get(provider) === config?.credential_ref) {
            credentialReferenceMemory.delete(provider);
        }
        delete config?.credential_ref;
        return label("LLM API session credential expired; enter the API key again.", "LLM API 会话凭证已失效，请重新输入 API Key。");
    }
    if (message === "请先配置提示词优化 API") {
        return label("Configure an API key or the corresponding environment variable.", "请配置 API Key 或对应环境变量。");
    }
    return message;
}

export function registerAutoOptimizerHandler(app, handler) {
    autoOptimizerHandlers.add(handler);
    if (!autoOptimizerQueueInstalled && typeof app?.queuePrompt === "function") {
        const original = app.queuePrompt.bind(app);
        app.queuePrompt = async function (...args) {
            for (const item of [...autoOptimizerHandlers]) await item();
            return original(...args);
        };
        autoOptimizerQueueInstalled = true;
    }
    return () => autoOptimizerHandlers.delete(handler);
}

function make(tag, className = "", text = "") {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text) item.textContent = text;
    return item;
}

async function fetchJson(api, path, options = {}) {
    const response = await api.fetchApi(path, options);
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; }
    catch { throw new Error(`Prompt optimizer returned invalid JSON (HTTP ${response.status})`); }
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
}

function cloudTaskName(value) {
    return ({ t2v: "T2VA", i2v: "I2VA", l2v: "L2VA", fl2v: "FL2VA", ref2v: "Ref2VA" })[String(value)] || String(value || "T2VA");
}

function activeEntries(media, prefix) {
    return [...(media instanceof Map ? media.entries() : [])]
        .filter(([slot, entry]) => slot.startsWith(prefix) && entry?.name)
        .sort((a, b) => Number(a[0].split("_").pop()) - Number(b[0].split("_").pop()));
}

export function cloudOptimizerMediaSpecs(task, media) {
    const result = [];
    if (task === "i2v" || task === "fl2v") {
        if (media.has("first_frame")) result.push({ slot: "first_frame", kind: "image", label: "<Picture 1>" });
        if (task === "fl2v" && media.has("last_frame")) result.push({ slot: "last_frame", kind: "image", label: "<Picture 2>" });
        return result;
    }
    if (task !== "ref2v") return result;
    activeEntries(media, "ref_image_").forEach(([slot], index) => result.push({ slot, kind: "image", label: `<Picture ${index + 1}>` }));
    activeEntries(media, "ref_video_").forEach(([slot], index) => result.push({ slot, kind: "video", label: `<Video ${index + 1}>` }));
    activeEntries(media, "ref_audio_").forEach(([slot], index) => result.push({ slot, kind: "audio", label: `<Audio ${index + 1}>` }));
    return result;
}

function lowImageData(url) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.crossOrigin = "anonymous";
        image.onload = () => {
            const scale = Math.min(1, 512 / Math.max(image.naturalWidth, image.naturalHeight));
            const canvas = document.createElement("canvas");
            canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
            canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
            canvas.getContext("2d", { alpha: false }).drawImage(image, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL("image/jpeg", 0.42));
        };
        image.onerror = () => reject(new Error("Unable to read visual reference"));
        image.src = url;
    });
}

function lowVideoFrames(url) {
    return new Promise((resolve, reject) => {
        const video = document.createElement("video");
        video.crossOrigin = "anonymous";
        video.muted = true;
        video.preload = "metadata";
        video.onloadedmetadata = async () => {
            try {
                const duration = Number.isFinite(video.duration) ? video.duration : 0;
                const times = [0, duration * 0.5, Math.max(0, duration - 0.05)];
                const frames = [];
                for (const time of times) {
                    await new Promise((done, fail) => {
                        video.onseeked = done;
                        video.onerror = () => fail(new Error("Unable to seek visual reference"));
                        if (video.currentTime === time) done();
                        else video.currentTime = time;
                    });
                    const scale = Math.min(1, 512 / Math.max(video.videoWidth, video.videoHeight));
                    const canvas = document.createElement("canvas");
                    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
                    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
                    canvas.getContext("2d", { alpha: false }).drawImage(video, 0, 0, canvas.width, canvas.height);
                    frames.push(canvas.toDataURL("image/jpeg", 0.42));
                }
                resolve(frames);
            } catch (error) { reject(error); }
        };
        video.onerror = () => reject(new Error("Unable to read visual reference"));
        video.src = url;
    });
}

async function optimizerMediaPayload({ api, specs, media, readMedia, inputMediaUrl, provider }) {
    const payload = [];
    const runninghub = ["runninghub", "runninghub_overseas"].includes(provider);
    let runninghubImages = 0;
    let runninghubVideo = false;
    for (const spec of specs) {
        const entry = media.get(spec.slot);
        if (!entry) continue;
        const item = { kind: spec.kind, label: spec.label };
        if (readMedia && spec.kind === "image") {
            if (!runninghub || runninghubImages < 8) item.images = [await lowImageData(inputMediaUrl(api, entry.name))];
            runninghubImages += 1;
        } else if (readMedia && spec.kind === "video") {
            if (runninghub) {
                if (!runninghubVideo) item.source_name = entry.name;
                runninghubVideo = true;
            } else item.images = await lowVideoFrames(inputMediaUrl(api, entry.name));
        }
        payload.push(item);
    }
    return payload;
}

function optimizerStyle() {
    return `<style>
      .gh-opt-bar{flex-wrap:wrap;min-width:0;max-width:100%}.gh-opt-action{display:flex;align-items:center;gap:6px;max-width:100%;flex-wrap:wrap}.gh-opt-timing{box-sizing:border-box;max-width:100%;font-size:13px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap;padding:4px 7px;border-radius:5px;background:#26323e}.gh-opt-timing[hidden],.gh-opt-cancel[hidden]{display:none}.gh-opt-timing[data-state=running]{color:#ffc04d;background:#493719}.gh-opt-timing[data-state=success]{color:#7be1a0;background:#193d2d}.gh-opt-timing[data-state=failure]{color:#ff9898;background:#49252b}.gh-opt-timing[data-state=cancelled]{color:#b7c4cf;background:#2c3943}
      .gh-opt-bar{display:flex;align-items:center;gap:5px;margin:5px 0}.gh-opt-bar button{border:1px solid #385163;border-radius:4px;background:#152633;color:#9fc0cc;padding:4px 7px;cursor:pointer}.gh-opt-overlay{position:fixed;inset:0;z-index:10050;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.58)}.gh-opt-dialog{box-sizing:border-box;width:min(470px,calc(100vw - 30px));max-height:calc(100dvh - 30px);overflow:auto;padding:14px;border:1px solid #344958;border-radius:9px;background:#17222c;color:#d7e3ec;box-shadow:0 18px 50px rgba(0,0,0,.5);font:12px Arial,sans-serif}.gh-opt-title{margin-bottom:11px}.gh-opt-row{display:grid;grid-template-columns:140px minmax(0,1fr);align-items:center;gap:8px;min-height:37px}.gh-opt-row input,.gh-opt-row select{box-sizing:border-box;width:100%;padding:6px;border:1px solid #3a4d5b;border-radius:4px;background:#1d2b36;color:#dce7ee}.gh-opt-check{justify-self:end;width:auto!important}.gh-opt-actions{display:flex;justify-content:flex-end;gap:7px;margin-top:18px}.gh-opt-actions button{padding:5px 12px;border:1px solid #3a4d5b;border-radius:4px;background:#1d2b36;color:#cbd8e0;cursor:pointer}.gh-opt-hidden{display:none!important}
    </style>`;
}

export function createOptimizerTimingBadge(label, clock = {}) {
    const now = clock.now || (() => performance.now());
    const schedule = clock.setInterval || globalThis.setInterval;
    const unschedule = clock.clearInterval || globalThis.clearInterval;
    const element = make("span", "gh-opt-timing");
    element.hidden = true;
    element.setAttribute("role", "status");
    let started = 0, interval = null, elapsed = 0, automatic = false, state = "idle";
    const stop = () => { if (interval !== null) unschedule(interval); interval = null; };
    function render() {
        element.setAttribute("data-state", state);
        const auto = automatic ? label("Auto optimization ", "自动优化 ") : "";
        element.textContent = state === "running"
            ? `● ${automatic ? label("Auto optimizing", "自动优化中") : label("Optimizing", "优化中")} ${elapsed.toFixed(1)}s`
            : state === "cancelled" ? `■ ${auto}${label("Cancelled", "已取消")} ${elapsed.toFixed(2)}s`
            : `${state === "success" ? "✓" : "✕"} ${auto}${elapsed.toFixed(2)}s`;
    }
    return { element,
        start(auto = false, startTime = now()) {
            stop(); started = startTime; elapsed = 0; automatic = auto; state = "running";
            element.hidden = false; element.setAttribute("aria-live", "off"); render();
            interval = schedule(() => { elapsed = Math.max(0, (now() - started) / 1000); render(); }, 100);
        },
        finish(result) {
            if (state !== "running") return elapsed;
            elapsed = Math.max(0, (now() - started) / 1000); state = result; stop();
            element.setAttribute("aria-live", "polite"); render(); return elapsed;
        },
        reset() { stop(); state = "idle"; elapsed = 0; element.hidden = true; },
        destroy: stop,
    };
}

// UI-only latest successful snapshot. Reuse the existing persisted pair.
export function validateCloudPromptHistory(state = {}) {
    const allowed = new Set(['optimizer_state_version', 'config', 'original_prompt', 'optimized_prompt', 'optimizer_report', 'report']);
    if (!state || typeof state !== 'object' || Array.isArray(state) || Object.keys(state).some(key => !allowed.has(key))) {
        throw new Error('Invalid Cloud optimizer history/state fields.');
    }
    const present = 'original_prompt' in state || 'optimized_prompt' in state;
    if (present && (typeof state.original_prompt !== 'string' || typeof state.optimized_prompt !== 'string')) {
        throw new Error('Prompt history before/after must both be strings.');
    }
    const pair = {original_prompt: state.original_prompt ?? '', optimized_prompt: state.optimized_prompt ?? ''};
    if (new Blob([JSON.stringify(pair)]).size > 262144) {
        throw new Error('Prompt history exceeds 256 KiB / 提示词历史超过 256 KiB，未保存或截断。');
    }
    return pair;
}

export function createPromptOptimizerController(options) {
    // UI adapters own task/media semantics; defaults preserve the Cloud policy.
    const resolveProfile = options.resolveProfile || resolveCloudPromptProfile;
    let settings = sanitizeOptimizerConfig({prompt_profile: "auto", ...(options.initialState?.config || {})});
    let closeSettings = null;
    let optimizedPrompt = String(options.initialState?.optimized_prompt || "");
    let report = String(options.initialState?.report || "");
    let previousPrompt = String(options.initialState?.original_prompt || "");
    let running = false;
    let requestId = "";
    let abortController = null;
    let requestSent = false;
    let revision = 0;
    let disposed = false;

    const bar = make("div", "gh-opt-bar");
    bar.innerHTML = optimizerStyle();
    const optimize = make("button", "gh-opt-run", options.label("Optimize prompt", "优化提示词"));
    const configure = make("button", "gh-opt-configure", "⚙ " + options.label("LLM Prompt Optimization Configuration", "LLM提示词优化配置"));
    const timing = createOptimizerTimingBadge(options.label);
    const cancel = make("button", "gh-opt-cancel", options.label("Cancel", "取消"));
    cancel.hidden = true;
    const action = make("div", "gh-opt-action");
    action.append(optimize, timing.element, cancel);
    bar.append(action, configure);

    function stateForSerialization() {
        validateCloudPromptHistory({original_prompt: previousPrompt, optimized_prompt: optimizedPrompt});
        return {
            optimizer_state_version: OPTIMIZER_STATE_VERSION,
            config: serializePublicOptimizerConfig(settings),
            optimized_prompt: optimizedPrompt,
            optimizer_report: report,
            original_prompt: previousPrompt,
        };
    }

    function notify() {
        if (!disposed) options.onStateChange?.(stateForSerialization());
    }

    async function loadSettings() {
        let defaults = {};
        try { defaults = await fetchJson(options.api, `${OPTIMIZER_ROUTE}/config`, { cache: "no-store" }); }
        catch (error) {
            if (!Object.keys(settings).length) throw error;
        }
        settings = sanitizeOptimizerConfig({ ...defaults, ...settings });
        if (settings.mode !== "local") { try { await refreshOptimizerCredentialStatus(options.api, settings.provider || "runninghub"); } catch {} }
        return withMemoryOptimizerCredentials(settings);
    }

    function openSettings() {
        return loadSettings().then(current => {
            closeSettings?.();
            const overlay = make("div", "gh-opt-overlay");
            const dialog = make("div", "gh-opt-dialog");
            overlay.append(dialog);
            dialog.append(make("div", "gh-opt-title", options.label("LLM Prompt Optimization Configuration", "LLM提示词优化配置")));
            const row = (title, control) => { const wrap = make("label", "gh-opt-row"); wrap.append(make("span", "", title), control); dialog.append(wrap); return wrap; };
            const mode = make("select"); mode.append(new Option(options.label("Online API", "在线 API"), "api"), new Option(options.label("Local vision model", "本地视觉模型"), "local")); mode.value = current.mode || "api"; row(options.label("Optimization mode", "优化方式"), mode);
            const provider = make("select"); for (const [value, preset] of Object.entries(OPTIMIZER_PROVIDERS)) provider.append(new Option(preset.label, value)); provider.value = current.provider || "runninghub"; row(options.label("Provider", "平台"), provider);
            const key = make("input"); key.type = "password"; key.autocomplete = "off"; key.value = ""; row("API Key", key);
            const credentialStatus = make("span", "gh-opt-credential-status");
            row(options.label("Credential status", "凭证状态"), credentialStatus);
            const refreshCredentialStatus = () => {
                credentialStatus.textContent = optimizerCredentialStatus({ ...settings, provider: provider.value }, options.label);
                key.placeholder = credentialStatus.textContent;
            };
            refreshCredentialStatus();
            credentialStatus.hidden = true;
            const model = make("input"); model.value = current.model || OPTIMIZER_PROVIDERS[provider.value]?.model || "";
            let catalog;
            createOptimizerCredentialPanel({api:options.api, provider, key, host:dialog, label:options.label, onChange:() => catalog?.refresh()});
            const modelHost = make("div"); row(options.label("Model", "模型"), modelHost);
            const maxTokens = make("input"); maxTokens.type = "number"; maxTokens.min = "512"; maxTokens.max = "8192"; maxTokens.step = "512"; maxTokens.value = String(current.max_tokens || 4096); row(options.label("Maximum output tokens", "最大输出 Tokens"), maxTokens);
            const language = make("select"); language.append(new Option("中文", "中文"), new Option("English", "English")); language.value = current.output_language || "中文"; row(options.label("Output language", "输出语言"), language);
            const readMedia = make("input", "gh-opt-check"); readMedia.type = "checkbox"; readMedia.checked = current.read_media !== false; row(options.label("Read visual references", "读取视觉素材"), readMedia);
            catalog = createApiModelSelector({api:options.api, provider, mode, model, readMedia, providerModels:current.provider_models, label:options.label});
            modelHost.append(catalog.root); catalog.refresh();
            mode.onchange = () => catalog.refresh();
            const autoOptimize = make("input", "gh-opt-check"); autoOptimize.type = "checkbox"; autoOptimize.checked = Boolean(current.auto_optimize); row(options.label("Automatic optimization before run", "运行前自动优化提示词"), autoOptimize);
            const profile = make("select", "gh-opt-profile");
            for (const [value, en, zh] of [["auto", "Automatic", "自动推荐"], ["concise", "Concise", "精简"], ["structured", "Structured", "结构化"]]) profile.append(new Option(options.label(en, zh), value));
            profile.value = current.prompt_profile || "auto";
            row(options.label("Prompt style", "提示词风格"), profile);
            const recommendation = make("div", "gh-opt-profile-recommendation"); dialog.append(recommendation);
            const refreshRecommendation = () => {
                recommendation.hidden = profile.value !== "auto";
                recommendation.textContent = options.label("Current recommendation: ", "当前推荐：") + (resolveProfile("auto", options.getTask()) === "structured" ? (options.resolveProfile ? options.label("Structured", "结构化") : options.label("Structured (Ref2V)", "结构化（Ref2V）")) : options.label("Concise", "精简"));
            };
            profile.onchange = refreshRecommendation; refreshRecommendation();
            // Mode/linked model changes are read live; the two model families
            // use the same profile mapping for every supported task.
            const recommendationTimer = setInterval(refreshRecommendation, 200);
            recommendationTimer.unref?.();
            const actions = make("div", "gh-opt-actions");
            const cancel = make("button", "", options.label("Cancel", "取消"));
            const save = make("button", "", options.label("Save", "保存"));
            actions.append(cancel, save); dialog.append(actions);
            const refreshProvider = () => {
                key.value = "";
                refreshCredentialStatus();
                catalog.providerChanged();
            };
            provider.onchange = refreshProvider;
            const close = () => { catalog.dispose(); clearInterval(recommendationTimer); key.value = ""; overlay.remove(); closeSettings = null; };
            closeSettings = close;
            cancel.onclick = close;
            overlay.onpointerdown = event => { if (event.target === overlay) close(); };
            save.onclick = async () => {
                if (save.disabled) return;
                save.disabled = true;
                provider.disabled = mode.disabled = true;
                try {
                    const preset = OPTIMIZER_PROVIDERS[provider.value] || OPTIMIZER_PROVIDERS.custom;
                    const body = {
                        mode: mode.value,
                        provider: provider.value,
                        api_url: provider.value === "custom" ? current.api_url || "" : preset.url,
                        protocol: preset.protocol,
                        model: model.value,
                        max_tokens: Math.max(512, Math.min(8192, Number(maxTokens.value) || 4096)),
                        output_language: language.value,
                        read_media: readMedia.checked,
                        auto_optimize: autoOptimize.checked,
                        prompt_profile: profile.value,
                    };
                    if (mode.value !== "local" && key.value) {
                        const exchange = registerEphemeralOptimizerSecret(options.api, body.provider, key.value);
                        key.value = "";
                        await exchange;
                        await catalog.refresh();
                    }
                    await catalog.validate();
                    body.model = model.value.trim();
                    settings = sanitizeOptimizerConfig({ ...body, environment_api_key_providers: current.environment_api_key_providers || [] });
                    notify();
                    close();
                } catch (error) {
                    alert(error?.message || options.label("Unable to save prompt optimizer settings", "无法保存提示词优化设置"));
                } finally { save.disabled = provider.disabled = mode.disabled = false; }
            };
            document.body.append(overlay);
        }).catch(error => alert(error?.message || String(error)));
    }

    async function run({ automatic = false } = {}) {
        if (running || disposed) return false;
        if (automatic && (options.node?.graph !== options.app?.graph
            || (options.node?.mode != null && options.node.mode !== 0))) return false;
        const task = options.getTask();
        if (!(options.supportedTasks || ["t2v", "i2v", "fl2v", "ref2v"]).includes(task)) return false;
        const startedAt = performance.now();
        const sourcePrompt = String(options.getPrompt() || "");
        const operationRevision = revision;
        running = true;
        let config = {};
        requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
        abortController = new AbortController();
        requestSent = false;
        optimize.disabled = true;
        configure.disabled = true;
        const timingStarted = !automatic || Boolean(settings.auto_optimize);
        if (timingStarted) { timing.start(automatic, startedAt); cancel.hidden = false; }
        try {
            config = await loadSettings();
            abortController.signal.throwIfAborted();
            if (automatic && !config.auto_optimize) { if (timingStarted) timing.reset(); return false; }
            if (automatic && !timingStarted) { timing.start(true, startedAt); cancel.hidden = false; }
            if (config.mode !== "local" && !config.has_api_key) {
                const message = options.label("Configure an API key or the corresponding environment variable.", "请配置 API Key 或对应环境变量。");
                const elapsed = timing.finish("failure");
                report = JSON.stringify({ status: "failed", error: message, optimizer_frontend_elapsed_seconds: elapsed });
                notify();
                if (!automatic) { alert(message); openSettings(); }
                return false;
            }
            let previousProfile;
            try { previousProfile = JSON.parse(report).resolved_prompt_profile; } catch {}
            const resolvedProfile = resolveProfile(config.prompt_profile || "auto", task);
            if (optimizedPrompt && sourcePrompt === optimizedPrompt && previousProfile === resolvedProfile) { timing.reset(); return true; }
            await options.prepareMedia?.();
            const media = options.getMedia();
            const specs = options.mediaSpecs ? await options.mediaSpecs(task, media) : cloudOptimizerMediaSpecs(task, media);
            const mediaPayload = await optimizerMediaPayload({
                api: options.api,
                specs,
                media,
                readMedia: config.read_media !== false,
                inputMediaUrl: options.inputMediaUrl,
                provider: config.provider,
            });
            const payload = {
                request_id: requestId,
                prompt: sourcePrompt,
                task: options.payloadTask ? options.payloadTask(task) : cloudTaskName(task),
                duration: Number(options.getDuration() || 5),
                media: mediaPayload,
                context: {
                    main_mode: task === "ref2v" ? "all_reference" : "text_keyframes",
                    keyframes: specs.filter(item => item.slot === "first_frame" || item.slot === "last_frame").map(item => ({ label: item.label, role: item.slot === "first_frame" ? "exact_first_frame" : "exact_last_frame" })),
                },
                tag_contract: options.tagContract || "gh_media_v1",
                config: resolveOptimizerCredential(config),
            };
            abortController.signal.throwIfAborted();
            requestSent = true;
            const data = await fetchJson(options.api, `${OPTIMIZER_ROUTE}/optimize`, {
                method: "POST",
                signal: abortController.signal,
                body: new Blob([JSON.stringify(payload)], { type: "application/json" }),
            });
            abortController.signal.throwIfAborted();
            if (operationRevision !== revision || options.getPrompt() !== sourcePrompt) {
                timing.finish('cancelled');
                return false;
            }
            if (typeof data.prompt !== 'string' || !data.prompt.trim()) throw new Error('Optimizer returned an invalid prompt.');
            validateCloudPromptHistory({original_prompt: sourcePrompt, optimized_prompt: data.prompt});
            const elapsed = timing.finish("success");
            previousPrompt = sourcePrompt;
            optimizedPrompt = String(data.prompt || "");
            report = String(data.report || JSON.stringify({ status: "optimized", task: cloudTaskName(task) }, null, 2));
            let details;
            try { details = JSON.parse(report); } catch { details = { report }; }
            if (!details || typeof details !== "object" || Array.isArray(details)) details = { report };
            report = JSON.stringify({ ...details, requested_prompt_profile: config.prompt_profile || "auto", resolved_prompt_profile: resolvedProfile, optimizer_frontend_elapsed_seconds: elapsed }, null, 2);
            options.setPrompt(optimizedPrompt);
            notify();
            return true;
        } catch (error) {
            if (operationRevision !== revision || disposed) return false;
            const cancelled = abortController?.signal.aborted || error?.name === "AbortError";
            const elapsed = timing.finish(cancelled ? "cancelled" : "failure");
            const message = optimizerCredentialError(error, config, options.label);
            report = JSON.stringify({ status: cancelled ? "cancelled" : "failed", task: cloudTaskName(task), error: message, optimizer_frontend_elapsed_seconds: elapsed }, null, 2);
            notify();
            if (!automatic && !cancelled) alert(message);
            return false;
        } finally {
            running = false;
            requestId = "";
            abortController = null;
            requestSent = false;
            optimize.disabled = false;
            configure.disabled = false;
            cancel.hidden = true;
            notify();
        }
    }

    async function cancelRun() {
        if (!running) return;
        abortController?.abort();
        timing.finish("cancelled");
        if (requestSent && requestId) {
            await options.api.fetchApi(`${OPTIMIZER_ROUTE}/cancel`, { method: "POST", body: new Blob([JSON.stringify({ request_id: requestId })], { type: "application/json" }) }).catch(() => {});
        }
    }

    function restore(raw) {
        const state = raw && typeof raw === "object" ? raw : {};
        const pair = validateCloudPromptHistory(state);
        if (![undefined, 1, OPTIMIZER_STATE_VERSION].includes(state.optimizer_state_version)) {
            throw new Error("Unsupported optimizer_state_version.");
        }
        rememberOptimizerCredentials(state.config || {});
        revision++;
        if (running) cancelRun();
        settings = sanitizeOptimizerConfig({prompt_profile: "auto", ...(state.config || settings)});
        optimizedPrompt = pair.optimized_prompt;
        report = String(state.optimizer_report || state.report || "");
        previousPrompt = pair.original_prompt;
        notify();
    }

    function invalidate() {
        revision++;
        if (running) cancelRun();
        report = "";
        notify();
    }

    configure.onclick = openSettings;
    cancel.onclick = cancelRun;
    optimize.onclick = () => run();
    const unregisterAuto = registerAutoOptimizerHandler(options.app, async () => {
        if (options.blockQueueOnFailure && options.node?.graph === options.app?.graph
            && (options.node?.mode == null || options.node.mode === 0)) {
            const config = await loadSettings();
            if (config.auto_optimize && !await run({ automatic: true }))
                throw new Error('本地自动优化未成功或已取消；未开始模型加载，请检查提示词优化状态。');
        } else await run({ automatic: true });
    });
    restore(options.initialState || {});
    return {
        element: bar,
        run,
        cancel: cancelRun,
        restore,
        invalidate,
        stateForSerialization,
        optimizedPrompt: () => options.getPrompt() === optimizedPrompt ? optimizedPrompt : "",
        report: () => report,
        enabled: () => Boolean(settings.auto_optimize),
        destroy() {
            disposed = true; revision++;
            closeSettings?.();
            unregisterAuto();
            cancelRun();
            timing.destroy();
        },
    };
}

export function resolveCloudPromptProfile(profile = "auto", task = "t2v") {
    if (!["auto", "concise", "structured"].includes(profile)) throw new Error("Invalid prompt_profile.");
    return profile === "auto" ? (["ref2v", "ref2va"].includes(String(task).toLowerCase()) ? "structured" : "concise") : profile;
}
