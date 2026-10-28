export const GH_CLOUD_IMAGE_SLOTS = [
    "first_frame",
    "last_frame",
    ...Array.from({ length: 9 }, (_, index) => `ref_image_${index + 1}`),
];
export const GH_CLOUD_VIDEO_SLOTS = Array.from(
    { length: 3 },
    (_, index) => `ref_video_${index + 1}`,
);
export const GH_CLOUD_AUDIO_SLOTS = [
    "hybrid_audio",
    ...Array.from({ length: 3 }, (_, index) => `ref_audio_${index + 1}`),
];
export const GH_CLOUD_MEDIA_SLOTS = [
    ...GH_CLOUD_IMAGE_SLOTS,
    ...GH_CLOUD_VIDEO_SLOTS,
    ...GH_CLOUD_AUDIO_SLOTS,
];

export function findWidget(node, name) {
    return node.widgets?.find((item) => item.name === name);
}

export function hideNativeWidget(item) {
    if (!item) return;
    item.hidden = true;
    item.options = item.options || {};
    item.options.hidden = true;
    item.computeSize = () => [0, -4];
    item.serialize = true;
}

export function mediaKindForSlot(slot) {
    if (slot === "first_frame" || slot === "last_frame" || slot.startsWith("ref_image_")) {
        return "image";
    }
    if (slot.startsWith("ref_video_")) return "video";
    if (slot === "hybrid_audio" || slot.startsWith("ref_audio_")) return "audio";
    return null;
}

export function mediaKindForFile(file) {
    const name = String(file?.name || "");
    const type = String(file?.type || "");
    if (type.startsWith("image/") || /\.(png|jpe?g|webp|bmp|gif)$/i.test(name)) return "image";
    if (type.startsWith("video/") || /\.(mp4|mov|webm|mkv|avi)$/i.test(name)) return "video";
    if (type.startsWith("audio/") || /\.(mp3|wav|flac|m4a|aac|ogg|oga|opus|wma|aif|aiff|alac|amr|caf|ac3|mp2)$/i.test(name)) return "audio";
    return null;
}

export function normalizeInputRelativeName(value) {
    const name = String(value || "").trim().replaceAll("\\", "/");
    if (!name || name.startsWith("/") || /^[A-Za-z]:/.test(name) || /^[A-Za-z][A-Za-z0-9+.-]*:/.test(name)) {
        throw new Error("Media must use a ComfyUI input-relative filename.");
    }
    const parts = name.split("/");
    if (parts.some((part) => !part || part === "." || part === "..")) {
        throw new Error("Media filename contains an invalid path segment.");
    }
    if (/\s+\[(input|output|temp)\]\s*$/i.test(name)) {
        throw new Error("Annotated paths are not valid Cloud media filenames.");
    }
    return parts.join("/");
}

export function inputMediaUrl(api, value) {
    if (!value) return "";
    const parts = normalizeInputRelativeName(value).split("/");
    const filename = parts.pop() || "";
    const query = new URLSearchParams({
        filename,
        type: "input",
        subfolder: parts.join("/"),
    });
    const path = `/view?${query.toString()}`;
    return typeof api.apiURL === "function" ? api.apiURL(path) : path;
}

export async function uploadInputMedia(api, file) {
    const body = new FormData();
    body.append("image", file, file.name);
    body.append("type", "input");
    const response = await api.fetchApi("/upload/image", { method: "POST", body });
    if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
    const result = await response.json();
    return normalizeInputRelativeName([result.subfolder, result.name].filter(Boolean).join("/"));
}

function hasMedia(media, slot) {
    return media instanceof Map ? media.has(slot) : Boolean(media?.[slot]);
}

export function deriveCloudTask(mode, media) {
    if (mode === "text_keyframes") {
        const first = hasMedia(media, "first_frame");
        const last = hasMedia(media, "last_frame");
        if (first && last) return "fl2v";
        if (first) return "i2v";
        if (last) return "l2v";
        return "t2v";
    }
    if (mode === "all_reference") {
        return GH_CLOUD_MEDIA_SLOTS.some(
            (slot) => slot.startsWith("ref_") && hasMedia(media, slot),
        ) ? "ref2v" : "t2v";
    }
    throw new Error(`Unknown cloud video mode: ${mode}`);
}

export function promptTagForSlot(mode, slot, media) {
    if (mode === "text_keyframes") {
        if (slot === "first_frame") return "<Picture 1>";
        if (slot === "last_frame") return "<Picture 2>";
        if (slot === "hybrid_audio") return "<Audio 1>";
        return "";
    }
    const groups = [
        ["ref_image_", "Picture"],
        ["ref_video_", "Video"],
        ["ref_audio_", "Audio"],
    ];
    for (const [prefix, label] of groups) {
        if (!slot.startsWith(prefix)) continue;
        const active = GH_CLOUD_MEDIA_SLOTS.filter(
            (candidate) => candidate.startsWith(prefix) && hasMedia(media, candidate),
        );
        const index = active.indexOf(slot);
        return index >= 0 ? `<${label} ${index + 1}>` : "";
    }
    return "";
}

export function parseCloudState(value) {
    if (!value || value === "(none)") return {};
    try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
}

export function cloudMediaPickerEntries(mode, media, label) {
    return GH_CLOUD_MEDIA_SLOTS.filter(slot => media.get(slot)?.name)
        .map(slot => {
            const tag = promptTagForSlot(mode, slot, media);
            const index = tag.match(/ (\d+)>$/)?.[1];
            const name = slot === "first_frame" ? label("First frame", "首帧")
                : slot === "last_frame" ? label("Last frame", "尾帧")
                : slot === "hybrid_audio" ? label("Hybrid audio", "音频1")
                : slot.startsWith("ref_image_") ? label(`Image ${index}`, `图片${index}`)
                : slot.startsWith("ref_video_") ? label(`Video ${index}`, `视频${index}`)
                : label(`Audio ${index}`, `音频${index}`);
            return { slot, tag, name, filename: String(media.get(slot).name) };
        }).filter(item => item.tag);
}

// Measure in untransformed CSS pixels, then map back to the canvas/node zoom.
// A fresh mirror also reflects textarea resizing, wrapping and scrollbar width.
export function getTextareaCaretRect(textarea, caretIndex) {
    const rect = textarea.getBoundingClientRect();
    const computed = getComputedStyle(textarea);
    const mirror = document.createElement("div");
    const marker = document.createElement("span");
    for (const property of ["font", "fontSize", "fontFamily", "fontWeight", "fontStyle", "fontVariant",
        "lineHeight", "letterSpacing", "wordSpacing", "textIndent", "textAlign", "textTransform",
        "direction", "tabSize", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
        "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth", "borderStyle",
        "whiteSpace", "wordWrap", "overflowWrap", "wordBreak"]) mirror.style[property] = computed[property];
    const borderX = parseFloat(computed.borderLeftWidth) + parseFloat(computed.borderRightWidth);
    Object.assign(mirror.style, {position: "fixed", left: "0", top: "0", visibility: "hidden",
        pointerEvents: "none", boxSizing: "border-box", height: "auto", overflow: "hidden",
        width: `${textarea.clientWidth + borderX}px`,
        whiteSpace: textarea.wrap === "off" ? "pre" : "pre-wrap", overflowWrap: "break-word"});
    mirror.setAttribute("aria-hidden", "true");
    mirror.textContent = textarea.value.slice(0, Math.max(0, caretIndex));
    marker.textContent = textarea.value.slice(Math.max(0, caretIndex)) || "\u200b";
    mirror.append(marker);
    document.body.append(mirror);
    try {
        const origin = mirror.getBoundingClientRect();
        const point = marker.getClientRects()[0] || marker.getBoundingClientRect();
        const lineHeight = parseFloat(computed.lineHeight) || parseFloat(computed.fontSize) * 1.2;
        const scaleX = rect.width / textarea.offsetWidth;
        const scaleY = rect.height / textarea.offsetHeight;
        const left = rect.left + (point.left - origin.left - textarea.scrollLeft) * scaleX;
        const top = rect.top + (point.top - origin.top - (lineHeight - point.height) / 2 - textarea.scrollTop) * scaleY;
        return {left, right: left, top, bottom: top + lineHeight * scaleY, width: 0, height: lineHeight * scaleY};
    } finally { mirror.remove(); }
}

export function attachCloudMediaPicker({ textarea, getMode, getMedia, label, onChange, getEntries }) {
    const menu = document.createElement("div");
    menu.className = "gh-cloud-picker";
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-label", label("Active media", "当前素材"));
    menu.hidden = true;
    document.body.append(menu);
    let selectedSlot = "";
    let composing = false;
    let activeMention = null;
    let previousValue = textarea.value;
    let pendingEdit = null;
    const close = () => { activeMention = null; menu.hidden = true; textarea.setAttribute("aria-expanded", "false"); };
    const query = () => {
        if (!activeMention || composing || document.activeElement !== textarea || textarea.selectionStart !== textarea.selectionEnd) return null;
        const end = textarea.selectionStart;
        const start = activeMention.atIndex;
        const text = textarea.value.slice(start + 1, end);
        if (textarea.value[start] !== "@" || end <= start || /[@\n<>]/.test(text)) return null;
        activeMention.caretIndex = end;
        activeMention.query = text;
        return { start, end, text: text.toLowerCase() };
    };
    const input = () => {
        const value = textarea.value;
        let start = 0;
        while (start < previousValue.length && start < value.length && previousValue[start] === value[start]) start++;
        let oldEnd = previousValue.length, newEnd = value.length;
        while (oldEnd > start && newEnd > start && previousValue[oldEnd - 1] === value[newEnd - 1]) { oldEnd--; newEnd--; }
        // Only a newly inserted @ creates a mention. No preceding-character boundary.
        if (pendingEdit) { start = pendingEdit.start; newEnd = start + pendingEdit.data.length; }
        const inserted = value.slice(start, Math.min(newEnd, textarea.selectionStart));
        const at = inserted.lastIndexOf("@");
        if (at >= 0) {
            activeMention = {atIndex: start + at, caretIndex: textarea.selectionStart, query: ""};
            selectedSlot = "";
        }
        previousValue = value;
        pendingEdit = null;
        if (!composing) refresh();
    };
    const beforeinput = event => {
        pendingEdit = event.inputType?.startsWith("insert") && typeof event.data === "string"
            ? {start: textarea.selectionStart, data: event.data} : null;
    };
    const entries = q => (getEntries ? getEntries() : cloudMediaPickerEntries(getMode(), getMedia(), label))
        .filter(item => `${item.name} ${item.filename} ${item.tag}`.toLowerCase().includes(q.text));
    const insert = slot => {
        const q = query();
        const current = q && entries(q).find(item => item.slot === slot);
        if (!current) { refresh(); return; }
        textarea.setRangeText(current.tag, q.start, q.end, "end");
        previousValue = textarea.value;
        close();
        onChange();
        textarea.focus({ preventScroll: true });
    };
    function refresh() {
        const q = query();
        if (!q) { close(); return; }
        const items = entries(q);
        if (!items.some(item => item.slot === selectedSlot)) selectedSlot = items[0]?.slot || "";
        menu.replaceChildren();
        if (!items.length) {
            const empty = document.createElement("div");
            empty.className = "gh-cloud-picker-empty";
            empty.textContent = label("No matching active media", "没有匹配的素材");
            menu.append(empty);
        }
        for (const item of items) {
            const row = document.createElement("button");
            row.type = "button";
            row.className = "gh-cloud-picker-row";
            row.setAttribute("role", "option");
            row.setAttribute("aria-selected", String(item.slot === selectedSlot));
            row.title = `${item.filename}\n${item.tag}`;
            const name = document.createElement("span"); name.textContent = `@${item.name}`;
            const file = document.createElement("span"); file.className = "gh-cloud-picker-file"; file.textContent = item.filename;
            row.append(name, file);
            row.onpointerdown = event => event.preventDefault();
            row.onclick = () => insert(item.slot);
            menu.append(row);
        }
        const rect = textarea.getBoundingClientRect();
        const nodeRect = textarea.closest(".gh-cloud-video-root, .gh-local-video-root")?.getBoundingClientRect() || rect;
        const bounds = {left: Math.max(8, nodeRect.left), right: Math.min(innerWidth - 8, nodeRect.right),
            top: Math.max(8, nodeRect.top), bottom: Math.min(innerHeight - 8, nodeRect.bottom)};
        const caret = getTextareaCaretRect(textarea, q.start);
        // Scrolling the mention outside the textarea/node should hide its popup.
        if (caret.bottom < Math.max(rect.top, bounds.top) || caret.top > Math.min(rect.bottom, bounds.bottom)
            || bounds.right <= bounds.left || bounds.bottom <= bounds.top) { close(); return; }
        const width = Math.max(0, Math.min(380, rect.width, bounds.right - bounds.left));
        menu.style.width = `${width}px`;
        menu.style.left = `${Math.max(bounds.left, Math.min(caret.left, bounds.right - width))}px`;
        menu.style.maxHeight = "220px";
        menu.style.bottom = "auto";
        menu.hidden = false;
        const desired = Math.min(220, menu.scrollHeight + 2);
        const below = Math.max(0, bounds.bottom - caret.bottom - 3);
        const above = Math.max(0, caret.top - bounds.top - 3);
        const upwards = below < desired && above > below;
        const height = Math.min(desired, upwards ? above : below);
        if (height < 20) { close(); return; }
        menu.style.maxHeight = `${height}px`;
        menu.style.top = `${upwards ? caret.top - height - 3 : caret.bottom + 3}px`;
        textarea.setAttribute("aria-expanded", "true");
        menu.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    }
    const keydown = event => {
        if (event.isComposing || menu.hidden) return;
        if (!["ArrowUp", "ArrowDown", "Enter", "Escape"].includes(event.key)) return;
        event.preventDefault(); event.stopPropagation();
        if (event.key === "Escape") { close(); return; }
        const q = query();
        const items = q ? entries(q) : [];
        if (event.key === "Enter") { insert(selectedSlot); return; }
        if (items.length) {
            const index = items.findIndex(item => item.slot === selectedSlot);
            selectedSlot = items[(index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].slot;
        }
        refresh();
    };
    const startComposition = () => { composing = true; menu.hidden = true; };
    const endComposition = () => { composing = false; input(); };
    const bindings = [["beforeinput", beforeinput], ["input", input], ["click", refresh], ["keydown", keydown], ["blur", close],
        ["compositionstart", startComposition], ["compositionend", endComposition]];
    for (const [event, handler] of bindings) textarea.addEventListener(event, handler);
    const reposition = event => { if (!menu.hidden && event?.target !== menu) refresh(); };
    globalThis.addEventListener("resize", reposition);
    globalThis.addEventListener("scroll", reposition, true);
    return { refresh, close, destroy() {
        for (const [event, handler] of bindings) textarea.removeEventListener(event, handler);
        globalThis.removeEventListener("resize", reposition);
        globalThis.removeEventListener("scroll", reposition, true);
        menu.remove();
    } };
}

export function createCloudRatioSelector({getTask, getMode, label, onChange, adaptiveLabel}) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'gh-ratio-trigger'; button.value = 'adaptive';
    button.setAttribute('aria-haspopup','listbox');
    const popup = document.createElement('div'); popup.className = 'gh-ratio-popup'; popup.hidden = true;
    popup.setAttribute('role','listbox'); popup.setAttribute('aria-label',label('Aspect ratio','画幅比例'));
    document.body.append(popup);
    const values = ['adaptive','21:9','16:9','4:3','1:1','3:4','9:16'];
    const text = value => value !== 'adaptive' ? value : adaptiveLabel ? adaptiveLabel() : getMode() === 'all_reference' ? label('Adaptive','自适应')
        : ['i2v','fl2v'].includes(getTask()) ? label('Follow first frame','跟随首帧') : label('Adaptive · default 16:9','自适应 · 默认16:9');
    const icon = value => {
        const el = document.createElement('span'); el.className = 'gh-ratio-icon'; el.setAttribute('aria-hidden','true');
        const [w,h] = (value === 'adaptive' ? '16:9' : value).split(':').map(Number);
        el.style.width = `${22*w/Math.max(w,h)}px`; el.style.height = `${22*h/Math.max(w,h)}px`;
        if(value === 'adaptive') el.style.borderStyle = 'dashed';
        return el;
    };
    const close = () => {popup.hidden=true;button.setAttribute('aria-expanded','false');};
    function refresh() {
        const name = document.createElement('span');name.textContent=text(button.value);
        button.replaceChildren(icon(button.value),name);button.title=text(button.value);
        if(popup.hidden) return;
        const rect=button.getBoundingClientRect();
        const node=button.closest('.gh-cloud-video-root, .gh-local-video-root')?.getBoundingClientRect() || rect;
        const left=Math.max(8,node.left),right=Math.min(innerWidth-8,node.right);
        const width=Math.max(0,Math.min(340,right-left));
        Object.assign(popup.style,{width:`${width}px`,left:`${Math.max(left,Math.min(rect.left,right-width))}px`,top:`${rect.bottom+3}px`});
        popup.style.maxHeight=`${Math.max(40,Math.min(innerHeight-rect.bottom-10,node.bottom-rect.bottom-3))}px`;
    }
    for(const value of values) {
        const item=document.createElement('button');item.type='button';item.className='gh-ratio-item';item.value=value;
        item.setAttribute('role','option');
        item.onclick=()=>{button.value=value;close();refresh();onChange();button.focus({preventScroll:true});};
        popup.append(item);
    }
    button.onclick=()=>{
        popup.hidden=!popup.hidden;button.setAttribute('aria-expanded',String(!popup.hidden));
        for(const item of popup.children) {
            const name=document.createElement('span');name.textContent=text(item.value);
            item.replaceChildren(icon(item.value),name);item.setAttribute('aria-selected',String(item.value===button.value));
        }
        refresh();
    };
    const keydown=e=>{
        if(e.key==='Escape') {close();button.focus();return;}
        if(!['ArrowDown','ArrowUp','ArrowLeft','ArrowRight'].includes(e.key)) return;
        e.preventDefault();
        if(popup.hidden) button.onclick();
        const index=[...popup.children].indexOf(document.activeElement);
        popup.children[(index+(e.key==='ArrowUp'||e.key==='ArrowLeft'?-1:1)+values.length)%values.length].focus();
    };
    button.addEventListener('keydown',keydown);popup.addEventListener('keydown',keydown);
    const outside=e=>{if(!button.contains(e.target)&&!popup.contains(e.target))close();};
    globalThis.addEventListener('pointerdown',outside);
    globalThis.addEventListener('resize',refresh);
    const scroll=e=>{if(!popup.contains(e.target))refresh();};
    globalThis.addEventListener('scroll',scroll,true);
    refresh();
    return {button,refresh,destroy(){popup.remove();globalThis.removeEventListener('pointerdown',outside);globalThis.removeEventListener('resize',refresh);globalThis.removeEventListener('scroll',scroll,true);}};
}

export function createCloudPromptHistory({textarea,label,onApply,initialState={}}) {
    const root=document.createElement('div');root.className='gh-prompt-history';
    const tabs=document.createElement('div');tabs.className='gh-prompt-tabs';tabs.setAttribute('role','tablist');
    const view=document.createElement('div');view.className='gh-prompt-view';
    const actions=document.createElement('div');actions.className='gh-prompt-actions';
    const restore=document.createElement('button');restore.textContent=label('Restore original prompt','恢复原始提示词');restore.className='gh-prompt-restore';
    const apply=document.createElement('button');apply.textContent=label('Use optimized result','使用优化结果');apply.className='gh-prompt-apply';
    const header=document.createElement('div');header.className='gh-prompt-header';
    actions.append(restore,apply);header.append(tabs,actions);root.append(header,textarea,view);
    let before=initialState.original_prompt || '',after=initialState.optimized_prompt || '',available=Boolean(after),selected='current';
    function render() {
        textarea.hidden=selected!=='current';view.hidden=selected==='current';actions.hidden=!available;
        view.replaceChildren();
        for(const tab of tabs.children) tab.setAttribute('aria-selected',String(tab.value===selected));
        if (!available && selected !== 'current') {
            const empty=document.createElement('span');empty.textContent=label('No optimization history','暂无优化记录');
            view.append(empty);return;
        }
        const add=(title,value)=>{
            const box=document.createElement('div');box.className='gh-prompt-readonly';
            const heading=document.createElement('div');heading.textContent=title;
            const text=document.createElement('textarea');text.readOnly=true;text.value=value;text.setAttribute('aria-label',title);
            box.append(heading,text);view.append(box);
        };
        if(selected==='original'||selected==='compare') add('Before',before);
        if(selected==='optimized'||selected==='compare') add('After',after);
    }
    for(const [value,en,zh] of [['current','Current','当前'],['original','Original','原始'],['optimized','Optimized','优化后'],['compare','Compare','对比']]) {
        const tab=document.createElement('button');tab.value=value;tab.textContent=label(en,zh);tab.setAttribute('role','tab');
        tab.onclick=()=>{selected=value;render();};tabs.append(tab);
    }
    restore.onclick=()=>{if(available){onApply(before);selected='current';render();}};
    apply.onclick=()=>{if(available){onApply(after);selected='current';render();}};
    render();
    return {element:root,record(original,optimized){before=original;after=optimized;available=true;selected='current';render();},
        hydrate(state){before=state.original_prompt || '';after=state.optimized_prompt || '';available=Boolean(after);selected='current';render();},
        reset(){before=after='';available=false;selected='current';render();}};
}
