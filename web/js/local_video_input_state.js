import {validateCloudPromptHistory, serializePublicOptimizerConfig} from './prompt_optimizer_shared.js';
// Local-only persistence and media semantics. Model choices remain native widgets.
export const LOCAL_SLOTS = ['first_frame','last_frame','hybrid_audio',
    ...Array.from({length:9},(_,i)=>`ref_image_${i+1}`),
    ...Array.from({length:3},(_,i)=>`ref_video_${i+1}`),
    ...Array.from({length:3},(_,i)=>`ref_audio_${i+1}`)];
export function localKind(slot) { return slot.includes('audio') ? 'audio' : slot.includes('video') ? 'video' : 'image'; }
export function readLocalState(raw, fallback={}) {
    const state=typeof raw==='string' ? (raw ? JSON.parse(raw) : {}) : raw || {};
    if(Array.isArray(state) || typeof state!=='object' || Object.keys(state).some(k=>!['schema_version','mode','prompt','media','optimizer','ui'].includes(k))) throw new Error('Invalid Local state');
    if(state.schema_version!==undefined && state.schema_version!==1) throw new Error('Unsupported Local state version');
    const mode=state.mode ?? fallback.mode ?? 'text_keyframes', prompt=state.prompt ?? fallback.prompt ?? '';
    if(!['text_keyframes','all_reference'].includes(mode)||typeof prompt!=='string') throw new Error('Invalid Local mode/prompt');
    const seen=new Set(), media=state.media ?? [];
    if(!Array.isArray(media)) throw new Error('Invalid Local media');
    const clean=media.map(item=>{
        if(!Array.isArray(item)||item.length!==2) throw new Error('Invalid Local media');
        const [slot,entry]=item, kind=localKind(slot);
        const allowed=['name','kind',...(kind==='video'?['muted']:kind==='audio'?['trimStart','trimEnd']:[])];
        if(!LOCAL_SLOTS.includes(slot)||seen.has(slot)||!entry||Object.keys(entry).some(k=>!allowed.includes(k))) throw new Error('Invalid Local media fields');
        if(typeof entry.name!=='string'||!entry.name||entry.name.includes('\0')||entry.name.includes(':')||entry.name.replaceAll('\\','/').split('/').some(p=>!p||p==='.'||p==='..')) throw new Error('Invalid Local input filename');
        if(entry.kind!==undefined&&entry.kind!==kind) throw new Error('Invalid Local media kind');
        seen.add(slot);return [slot,{...entry,kind}];
    });
    const result={schema_version:1,mode,prompt,media:clean};
    if(state.optimizer!==undefined) {
        const scan=value=>{if(value&&typeof value==='object')for(const [key,item] of Object.entries(value)) {
            const normalized=key.replace(/([a-z])([A-Z])/g,'$1_$2').toLowerCase();
            if(/(?:api_?key|credential|secret|authorization|bearer|headers|base64)/.test(normalized))throw new Error('Forbidden Local optimizer persistence field');
            scan(item);
        }};
        scan(state.optimizer);
        validateCloudPromptHistory(state.optimizer);
        if(![undefined,1,2].includes(state.optimizer.optimizer_state_version))throw new Error('Unsupported optimizer_state_version');
        result.optimizer={...state.optimizer};
        if(state.optimizer.config) result.optimizer.config=serializePublicOptimizerConfig(state.optimizer.config);
        for(const key of ['report','optimizer_report']) if(key in state.optimizer && typeof state.optimizer[key]!=='string')throw new Error('Invalid optimizer report');
    }
    if(state.ui!==undefined) {
        if(!state.ui||typeof state.ui!=='object'||Array.isArray(state.ui)||Object.keys(state.ui).some(k=>k!=='models_collapsed'||typeof state.ui[k]!=='boolean'))throw new Error('Invalid Local UI state');
        result.ui={...state.ui};
    }
    return result;
}

export function localTask(mode, media) {
    if(mode==='all_reference')return 'ref2v';
    return media.has('first_frame') ? (media.has('last_frame')?'fl2v':'i2v') : media.has('last_frame')?'l2v':'t2v';
}
export function localMediaSpecs(mode, media, metadata=new Map(), {ignoreVideoAudio=false}={}) {
    const specs=[];
    const add=(slot,kind,index)=>specs.push({slot,kind,label:`<${kind==='image'?'Picture':kind==='video'?'Video':'Audio'} ${index}>`});
    if(mode!=='all_reference') {
        let picture=0;
        for(const slot of ['first_frame','last_frame'])if(media.has(slot))add(slot,'image',++picture);
        if(picture&&media.has('hybrid_audio'))add('hybrid_audio','audio',1);
        return specs;
    }
    let audio=0;
    // Match the legacy builder: sparse picture/video slot IDs, dense audio order.
    for(const slot of LOCAL_SLOTS.filter(s=>s.startsWith('ref_image_')))if(media.has(slot))add(slot,'image',Number(slot.split('_').pop()));
    for(const slot of LOCAL_SLOTS.filter(s=>s.startsWith('ref_video_')))if(media.has(slot)) {
        if(!ignoreVideoAudio&&!media.get(slot).muted && metadata.get(media.get(slot).name)?.has_audio)add(slot,'audio',++audio);
        add(slot,'video',Number(slot.split('_').pop()));
    }
    for(const slot of LOCAL_SLOTS.filter(s=>s.startsWith('ref_audio_')))if(media.has(slot))add(slot,'audio',++audio);
    return specs;
}
export function localPickerEntries(mode, media, metadata=new Map(), options={}) {
    const pendingAudio=mode==='all_reference'&&!options.ignoreVideoAudio&&[...media].some(([slot,entry])=>slot.startsWith('ref_video_')&&!entry.muted&&!metadata.has(entry.name));
    return localMediaSpecs(mode,media,metadata,options).filter(spec=>spec.kind!=='audio'||!pendingAudio).map(spec=>({slot:`${spec.slot}:${spec.kind}`,tag:spec.label,
        name:spec.kind==='audio'&&spec.slot.startsWith('ref_video_')?`视频原声${spec.label.match(/\d+/)[0]}`:
        spec.slot==='first_frame'?'首帧':spec.slot==='last_frame'?'尾帧':`${spec.kind==='image'?'图片':spec.kind==='video'?'视频':'音频'}${spec.label.match(/\d+/)[0]}`,
        filename:media.get(spec.slot).name}));
}
export function resolveLocalPromptProfile(profile='auto') {
    if(!['auto','concise','structured'].includes(profile))throw new Error('Invalid prompt_profile');
    return profile==='auto'?'structured':profile;
}
export async function uploadLocalMedia(api,file) {
    const form=new FormData();form.append('image',file,file.name);form.append('type','input');
    const response=await api.fetchApi('/upload/image',{method:'POST',body:form});
    if(!response.ok) throw new Error(`上传失败 / Upload failed (${response.status})`);
    const data=await response.json();
    return [data.subfolder,data.name].filter(Boolean).join('/');
}
