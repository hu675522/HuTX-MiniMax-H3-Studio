// HuTX-owned workbench contracts. No provider, storage or inference side effects.
import {cleanShot} from './workbench_sequence.js';
import {cleanClipEdit} from './workbench_edit.js';
export const VIDEO_NODE_TYPES = new Set(['GHLocalVideoInputDualEngineGH', 'GHLocalVideoInputGH']);
export const SPEECH_NODE_TYPES = new Set(['GHMultiSpeechInputGH', 'GHSpeechInputGH']);
const OUTPUT_TYPES = new Set(['SaveVideo', 'VHS_VideoCombine', 'SaveWEBM']);
export const widgetValue = (node, name) => node?.widgets?.find(item => item.name === name)?.value;
export const graphNodes = graph => (graph?._nodes || []).filter(node => node.mode !== 2 && node.mode !== 4);
const linkAt = (graph, id) => graph?.links instanceof Map ? graph.links.get(id) : graph?.links?.[id];
const nodeAt = (graph, id) => graph?.getNodeById?.(id) || graph?._nodes?.find(node => String(node.id) === String(id));

export function videoIdentity(file) {
    if (!file || typeof file !== 'object') return null;
    const {filename, subfolder = '', type = 'output'} = file;
    if (typeof filename !== 'string' || typeof subfolder !== 'string' || !['output', 'temp'].includes(type)) return null;
    if (!/\.(mp4|webm|mov|mkv|m4v)$/i.test(filename)) return null;
    if ([filename, subfolder].some(value => value.length > 1024 || /[\x00-\x1f\\:]/.test(value) || value.startsWith('/') || value.split('/').some(part => part === '..' || part === '.'))) return null;
    return {filename, subfolder, type};
}
export const videoKey = file => JSON.stringify([file.type, file.subfolder, file.filename]);
export function videoUrl(api, file, download = false) {
    const clean = videoIdentity(file);
    if (!clean) throw new Error('视频文件信息无效。');
    const query = new URLSearchParams(clean);
    if (download) query.set('download', '1');
    return api.apiURL('/view?' + query);
}

export function readWorkbenchState(graph) {
    const raw = graph?.extra?.hutx_workbench;
    const valid = [1,2,3].includes(raw?.schema_version);
    const shortlist = [], seen = new Set();
    for (const item of (valid && Array.isArray(raw.shortlist) ? raw.shortlist.slice(0, 100) : [])) {
        const file = videoIdentity(item), key = file && videoKey(file);
        if (!file || seen.has(key)) continue;
        seen.add(key);
        let edit;try{edit=cleanClipEdit(item.edit);}catch{continue;}
        shortlist.push({...file, title: typeof item.title === 'string' ? item.title.slice(0, 120) : file.filename,edit});
    }
    const shots = [];
    for (const item of (valid && Array.isArray(raw.shots) ? raw.shots.slice(0,32) : [])) {
        try {const shot=cleanShot(item);if(!shots.some(existing=>existing.id===shot.id))shots.push(shot);} catch {}
    }
    const job=valid?raw.assembly_job:null;
    const assembly_job=job&&/^[a-f0-9]{32}$/.test(job.job_id||'')&&['running','complete','error','cancelled'].includes(job.state)?{
        job_id:job.job_id,state:job.state,completed:Number.isInteger(job.completed)?Math.max(0,Math.min(33,job.completed)):0,
        total:Number.isInteger(job.total)?Math.max(0,Math.min(33,job.total)):0,result:videoIdentity(job.result),error:typeof job.error==='string'?job.error.slice(0,300):''}:null;
    return {schema_version: 3, project_id:valid && /^[a-z0-9-]{16,64}$/.test(raw.project_id || '') ? raw.project_id : '',
        project_name: valid && typeof raw.project_name === 'string' ? raw.project_name.slice(0, 120) : '未命名项目', shortlist, shots, assembly_job};
}
export function writeWorkbenchState(graph, state) {
    if (!graph) throw new Error('当前没有打开的工作流。');
    // Only these bounded metadata fields travel with a normal workflow save.
    if (Array.isArray(state.shots)) {if(state.shots.length>32)throw new Error('最多保存 32 个镜头。');state.shots.forEach(cleanShot);}
    if(Array.isArray(state.shortlist))state.shortlist.forEach(item=>cleanClipEdit(item.edit));
    const clean = readWorkbenchState({extra: {hutx_workbench: {...state, schema_version: 3}}});
    clean.project_id ||= crypto.randomUUID();
    if (new Blob([JSON.stringify(clean)]).size>8388608) throw new Error('项目镜头快照超过 8 MiB，请减少镜头或素材记录。');
    graph.extra ||= {};
    graph.extra.hutx_workbench = clean;
    graph.change?.();
    return clean;
}

export function historyVideos(history) {
    const result = [], seen = new Set();
    for (const [promptId, record] of Object.entries(history || {}).reverse()) {
        const prompt = record?.prompt?.[2];
        if (!prompt || !Object.values(prompt).some(node => VIDEO_NODE_TYPES.has(node?.class_type))) continue;
        for (const [nodeId, output] of Object.entries(record.outputs || {})) {
            for (const field of ['videos', 'gifs', 'images']) {
                for (const item of Array.isArray(output?.[field]) ? output[field] : []) {
                    const file = videoIdentity(item), key = file && videoKey(file);
                    if (!file || seen.has(key)) continue;
                    seen.add(key);
                    result.push({...file, promptId, nodeId, title: file.filename});
                }
            }
        }
    }
    return result.slice(0, 100);
}

export function hasVideoOutput(graph, source) {
    const pending = [source], visited = new Set();
    while (pending.length) {
        const node = pending.shift();
        if (!node || visited.has(node.id) || node.mode === 2) continue;
        visited.add(node.id);
        if (node !== source && node.mode !== 4 && OUTPUT_TYPES.has(node.type)) return true;
        for (const output of node.outputs || []) for (const id of output.links || []) {
            const link = linkAt(graph, id);
            if (link) pending.push(nodeAt(graph, link.target_id));
        }
    }
    return false;
}

export function validateGeneration(graph, source) {
    if (!source || !graphNodes(graph).includes(source)) throw new Error('请选择当前画布中启用的视频节点。');
    if (!VIDEO_NODE_TYPES.has(source.type)) throw new Error('当前节点不支持工作台生成。');
    if (!String(widgetValue(source, 'prompt') || '').trim()) throw new Error('请先填写镜头提示词。');
    if (!hasVideoOutput(graph, source)) throw new Error('当前镜头还没有连接视频保存节点。请补齐采样、解码和保存，或添加基础单采线路。');
    for (const input of source.inputs || []) {
        if (!/^driver_audio$|^reference_audio_[123]$/.test(input.name) || input.link == null) continue;
        const link = linkAt(graph, input.link), upstream = nodeAt(graph, link?.origin_id);
        if (upstream?.type === 'GHSpeechInputGH' && !widgetValue(upstream, 'adopted_audio_file')) throw new Error('连接的口播尚未采用，请先生成、试听并采用音频。');
        if (upstream?.type === 'GHMultiSpeechInputGH') {
            let role; try { role = JSON.parse(widgetValue(upstream, 'role_' + 'ABC'[link.origin_slot]) || '{}'); } catch { throw new Error('角色配置无效。'); }
            if (role.enabled !== false && role.text?.trim() && !role.adopted_audio_file) throw new Error('连接的角色尚未采用音频，请到「角色与声音」确认。');
        }
    }
    return true;
}

export function connectRoleAudio(graph, source, target) {
    if (source?.type !== 'GHMultiSpeechInputGH' || !VIDEO_NODE_TYPES.has(target?.type) || source.graph !== graph || target.graph !== graph) throw new Error('请在同一画布中选择多角色节点和视频节点。');
    const plan = [0, 1, 2].map(index => {
        const slot = target.inputs?.findIndex(input => input.name === `reference_audio_${index + 1}`);
        if (slot == null || slot < 0) throw new Error('目标节点缺少三路参考音频接口。');
        const linkId = target.inputs[slot].link;
        const current = linkAt(graph, linkId);
        if (linkId != null && (!current || String(current.origin_id) !== String(source.id) || current.origin_slot !== index)) throw new Error(`参考音频槽 ${index + 1} 已有其它连接，请先在画布确认接线。`);
        return {index, slot, existing: linkId != null};
    });
    const added = [];
    try {
        for (const {index, slot, existing} of plan) if (!existing) {
            const link = source.connect(index, target, slot);
            if (!link || target.inputs[slot].link == null) throw new Error('连接失败，已撤销本次新增接线。');
            added.push(slot);
        }
    } catch (error) { for (const slot of added) target.disconnectInput(slot); throw error; }
    graph.change?.();
    return plan.length;
}

// Lease the existing live editor instead of creating a second controller/TTS job.
export function leasePanel(node, host, onReturn = () => {}) {
    const panel = node?.hutxWorkbenchPanel, root = panel?.root || panel?.element;
    if (!root?.appendChild) throw new Error('节点编辑器尚未创建，请确认 HuTX 前端扩展已加载。');
    node.hutxWorkbenchLease?.release();
    const origin = panel.canvasHost || root.parentNode;
    const placeholder = document.createElement('div');
    placeholder.className = 'hutx-workbench-placeholder';
    const label = document.createElement('span'); label.textContent = '正在 HuTX总台编辑';
    const back = document.createElement('button'); back.type = 'button'; back.textContent = '返回画布面板';
    placeholder.append(label, back);
    if(root.parentNode)root.before(placeholder);
    else if(origin)origin.append(placeholder);
    host.append(root);
    let released = false;
    const lease = {node, panel, root, reclaim() {
        if(!released&&root.parentNode!==host)host.append(root);
    }, release() {
        if (released) return;
        released = true;
        if (placeholder.parentNode) placeholder.replaceWith(root);
        else if(origin)origin.append(root);
        else if(root.parentNode===host)root.remove();
        if (node.hutxWorkbenchLease === lease) delete node.hutxWorkbenchLease;
    }};
    back.onclick = () => { lease.release(); onReturn(); };
    node.hutxWorkbenchLease = lease;
    return lease;
}
