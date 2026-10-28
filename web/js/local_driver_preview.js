// A display-only projection. Never serialize connected audio as uploaded media.
export function driverSlotChoices(mode, target, media) {
    const reference=mode==='all_reference';
    const options=reference?[1,2,3].map(i=>[`ref_audio_${i}`,`参考音频槽 ${i}`]):[['hybrid_audio','Hybrid 音频']];
    let selected=target;
    if(target==='auto') {
        const last=Math.max(0,...[...media.keys()].filter(s=>/^ref_audio_[123]$/.test(s)).map(s=>Number(s.at(-1))));
        selected=reference?`ref_audio_${last+1}`:'hybrid_audio';
    }
    return {options,selected:options.some(([value])=>value===selected)?selected:'',automatic:target==='auto'};
}

export function connectedSpeechSource(node) {
    const input=node.inputs?.find(item=>item.name==='driver_audio');
    if(input?.link==null)return {message:'尚未连接 driver_audio：请将口播节点的 audio 输出接入这里。'};
    const link=node.graph?.links?.get?.(input.link)||node.graph?.links?.[input.link];
    const source=node.graph?.getNodeById(link?.origin_id);
    if(source?.type!=='GHSpeechInputGH'||link?.origin_slot!==0)
        return {message:'已连接 AUDIO；该上游需执行后才能确定音频，当前不提供已采用口播预览。'};
    const ref=source.widgets?.find(item=>item.name==='adopted_audio_file')?.value;
    if(!/^hutx-speech\/adopted\/[a-f0-9]{64}\.json$/.test(ref||''))
        return {message:'口播已接线，请先生成、试听并点击“采用此音频”。'};
    return {ref,sourceId:source.id};
}

export function connectedRoleSources(node) {
    return [1,2,3].map(index=>{
        const input=node.inputs?.find(item=>item.name===`reference_audio_${index}`);
        if(input?.link==null)return null;
        const link=node.graph?.links?.get?.(input.link)||node.graph?.links?.[input.link];
        const source=node.graph?.getNodeById(link?.origin_id);
        const slot=`ref_audio_${index}`,letter='ABC'[link?.origin_slot];
        if(source?.type==='GHMultiSpeechInputGH'&&letter){
            let role={};try{role=JSON.parse(source.widgets?.find(w=>w.name===`role_${letter}`)?.value||'{}');}catch{}
            if(role.enabled===false||!role.text?.trim())return null;
            const ref=role.adopted_audio_file;
            return {slot,name:role.name||`角色 ${letter}`,ref:/^hutx-speech\/adopted\/[a-f0-9]{64}\.json$/.test(ref||'')?ref:'',message:`角色 ${letter} 请先生成、试听并采用。`};
        }
        return {slot,name:`参考音频 ${index}`,ref:'',message:'该 AUDIO 需执行后确定，当前无已采用预览。'};
    }).filter(Boolean);
}

export function projectRoleMedia(mode,media,sources,audios){
    const projected=new Map(media),slots=[];
    if(!sources.length)return {media:projected,slots,message:''};
    if(mode!=='all_reference')return {media:projected,slots,message:'角色音频仅用于全能参考；文本/首尾帧请使用 driver_audio。',error:true};
    const messages=[];let error=false;
    for(const source of sources){
        if(media.has(source.slot)){messages.push(`${source.slot} 已有上传音频，请移除素材或断开接线。`);error=true;continue;}
        const audio=audios.get(source.ref);
        if(!audio){messages.push(source.ref?'正在读取角色音频，或快照已失效。':source.message);error=true;continue;}
        projected.set(source.slot,{name:audio.audio_file,kind:'audio'});slots.push(source.slot);
        messages.push(`${source.name} → ${source.slot} · ${audio.duration_seconds.toFixed(2)}s`);
    }
    const activeAudioSlots=[...projected.keys()].filter(slot=>/^ref_audio_[123]$/.test(slot)).sort();
    const mappings=sources.filter(source=>slots.includes(source.slot)).map(source=>{
        const ordinal=activeAudioSlots.indexOf(source.slot)+1;
        return `${source.name} = <Audio ${ordinal}>`;
    });
    const videoAudioIgnored=[...media].some(([slot,entry])=>slot.startsWith('ref_video_')&&!entry.muted);
    if(mappings.length)messages.push(`提示词调用：${mappings.join('，')}`);
    if(videoAudioIgnored)messages.push('角色音频接入期间，本次执行自动忽略参考视频原声；断开角色音频后恢复');
    return {media:projected,slots,message:messages.join('；'),error,ignoreVideoAudio:true};
}

export function projectDriverMedia(mode,media,metadata,settings,audio,{preview=false}={}) {
    const projected=new Map(media),fail=message=>({media:projected,message});
    if(!audio)return fail('');
    const ref=mode==='all_reference';
    if(settings.family!==(ref?'Ref2VA':'FL2VA'))return fail('请先确认与当前模式一致的口播模型家族。');
    let slot;
    if(ref) {
        if(!preview&&![...media.keys()].some(s=>/^ref_(image|video)_/.test(s)))return fail('请先添加参考图片或视频。');
        const audios=[...media.keys()].filter(s=>/^ref_audio_/.test(s)).sort();
        const videos=[...media].filter(([s,e])=>s.startsWith('ref_video_')&&!e.muted);
        if(videos.some(([,e])=>!metadata.has(e.name)))return fail('正在确认参考视频音轨，完成后显示口播标签。');
        const soundtrack=videos.some(([,e])=>metadata.get(e.name)?.has_audio);
        if((audios.length||soundtrack)&&settings.policy!=='use_connected_audio')return fail('存在其他音频，请明确选择使用连接口播作为驱动。');
        const last=audios.length?Number(audios.at(-1).split('_').at(-1)):0;
        slot=settings.target==='auto'?`ref_audio_${last+1}`:settings.target;
        if(!/^ref_audio_[123]$/.test(slot))return fail('没有可用参考音频槽，请选择要替换的口播槽位。');
        if(!media.has(slot)&&Number(slot.at(-1))<last)return fail('不能插入到已有音频之前，请选择后续槽位以保持编号。');
    } else {
        if(!media.has('first_frame')&&!media.has('last_frame'))return fail('口播驱动需要首帧或尾帧图片。');
        if(!['auto','hybrid_audio'].includes(settings.target))return fail('首帧/首尾帧口播请选择 Hybrid 音频槽。');
        if(media.has('hybrid_audio')&&settings.policy!=='use_connected_audio')return fail('已有 Hybrid 音频，请明确选择使用连接口播作为驱动。');
        slot='hybrid_audio';
    }
    projected.set(slot,{name:audio.audio_file,kind:'audio'});
    const missingVisual=ref&&![...media.keys()].some(s=>/^ref_(image|video)_/.test(s));
    return {media:projected,slot,message:`已连接采用口播 · ${audio.duration_seconds.toFixed(2)}s`+(missingVisual?'；请添加参考图片或视频后再生成。':'')};
}
