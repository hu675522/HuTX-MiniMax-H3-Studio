// Non-destructive clip edits. No generation, providers or external dependencies.
export const DEFAULT_EDIT = Object.freeze({trim_start:0, trim_end:null, volume:1, muted:false});
const MIN_SPAN = 1 / 24;
export function cleanClipEdit(raw) {
    if (raw == null) return {...DEFAULT_EDIT};
    if (typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).some(key=>!Object.hasOwn(DEFAULT_EDIT,key))) throw new Error('片段编辑参数无效。');
    const edit = {...DEFAULT_EDIT,...raw};
    const numeric = value=>typeof value==='number' && Number.isFinite(value);
    if (!numeric(edit.trim_start) || edit.trim_start<0 || edit.trim_start>=120 ||
        (edit.trim_end!==null && (!numeric(edit.trim_end) || edit.trim_end>120 || edit.trim_end-edit.trim_start<MIN_SPAN-1e-8)) ||
        !numeric(edit.volume) || edit.volume<0 || edit.volume>2 || typeof edit.muted!=='boolean') throw new Error('裁剪需至少保留一帧，音量范围为 0–200%。');
    return edit;
}
export function clipSpan(edit, duration) {
    edit=cleanClipEdit(edit);
    if (!Number.isFinite(duration) || duration<=0) return null;
    const end=edit.trim_end??duration;
    if (end>duration+0.001 || end-edit.trim_start<MIN_SPAN-1e-8) throw new Error('裁剪范围超出原片段，请调整入点和出点。');
    return Math.ceil((Math.min(end,duration)-edit.trim_start)*24-1e-7)/24;
}
export function sequenceDuration(clips, durations) {
    let seconds=0,unknown=0,invalid=0;
    for(const clip of clips){try{const span=clipSpan(clip.edit,durations(clip));if(span===null)unknown++;else seconds+=span;}catch{invalid++;}}
    return {seconds,unknown,invalid};
}
export function timeLabel(seconds) {
    return `${Math.floor(seconds/60)}:${(seconds%60).toFixed(2).padStart(5,'0')}`;
}

export function createClipEditor(file,index,{url,disabled=false,open=false,onToggle,onChange,onDuration,pauseOthers}) {
    const edit=cleanClipEdit(file.edit),root=document.createElement('details');root.className='wb-clip';root.open=open;
    const make=(tag,text='')=>{const node=document.createElement(tag);node.textContent=text;return node;};
    root.append(make('summary','裁剪与声音'));
    root.ontoggle=()=>{if(root.isConnected)onToggle?.(root.open);};
    const video=make('video');video.controls=true;video.preload='metadata';video.playsInline=true;
    video.setAttribute('aria-label',`片段 ${index+1} 裁剪预览`);video.volume=Math.min(1,edit.volume);video.muted=edit.muted||edit.volume===0;
    // Browser volume is capped at 100%; export applies the full 0–200% gain.
    const hint=make('p');hint.className='wb-hint';hint.textContent='读取本机片段时长…';
    const setHint=()=>{try{const span=clipSpan(edit,video.duration);hint.textContent=span===null?'完整时长待读取，导出时会按真实文件校验。':`原片 ${timeLabel(video.duration)} · 导出 ${timeLabel(span)}${edit.volume>1?' · 超过 100% 的增益仅在导出应用':''}`;}catch(error){hint.textContent=error.message;}};
    video.onloadedmetadata=()=>{onDuration?.(video.duration);setHint();if(edit.trim_start<video.duration)video.currentTime=edit.trim_start;};
    video.onerror=()=>{hint.textContent='无法读取片段，请确认文件仍在原目录。';onDuration?.(null);};
    video.onplay=()=>{pauseOthers?.(video);if(video.currentTime<edit.trim_start||video.currentTime>=(edit.trim_end??video.duration))video.currentTime=edit.trim_start;};
    video.ontimeupdate=()=>{if(!video.paused&&video.currentTime>=(edit.trim_end??video.duration)){video.pause();}};
    root.append(video,hint);
    const fields=make('div');fields.className='wb-clip-fields';
    const inputs={};
    for(const [key,label,value] of [['trim_start','入点（秒）',edit.trim_start],['trim_end','出点（秒）',edit.trim_end??''],['volume','音量（%）',Number((edit.volume*100).toFixed(6))]]){
        const box=make('label',label),input=make('input');input.type='number';input.min='0';input.max=key==='volume'?'200':'120';input.step='any';input.value=value;input.disabled=disabled;
        if(key==='trim_end')input.placeholder='留空至片尾';
        input.setAttribute('aria-label',`片段 ${index+1} ${label}`);inputs[key]=input;box.append(input);fields.append(box);
    }
    const muteBox=make('label','静音'),mute=make('input');mute.type='checkbox';mute.checked=edit.muted;mute.disabled=disabled;mute.setAttribute('aria-label',`片段 ${index+1} 静音`);muteBox.prepend(mute);fields.append(muteBox);
    const apply=()=>{
        Object.values(inputs).forEach(input=>input.setCustomValidity(''));
        try{
            const next=cleanClipEdit({trim_start:inputs.trim_start.value===''?NaN:Number(inputs.trim_start.value),trim_end:inputs.trim_end.value===''?null:Number(inputs.trim_end.value),volume:inputs.volume.value===''?NaN:Number(inputs.volume.value)/100,muted:mute.checked});
            if(Number.isFinite(video.duration))clipSpan(next,video.duration);
            onChange(next);
        }catch(error){hint.textContent='尚未保存：'+error.message;hint.setAttribute('role','alert');inputs.trim_start.setCustomValidity(error.message);}
    };
    Object.values(inputs).forEach(input=>input.onchange=apply);mute.onchange=apply;
    const actions=make('div');actions.className='wb-actions';
    for(const [label,action] of [['播放选段',()=>{video.currentTime=edit.trim_start;video.play().catch(()=>{hint.textContent='无法播放，请检查视频格式。';});}],['用当前位置设入点',()=>{inputs.trim_start.value=video.currentTime.toFixed(2);apply();}],['用当前位置设出点',()=>{inputs.trim_end.value=video.currentTime.toFixed(2);apply();}],['重置编辑',()=>onChange({...DEFAULT_EDIT})]]){
        const button=make('button',label);button.type='button';button.disabled=disabled;button.onclick=()=>{try{action();}catch(error){hint.textContent=error.message;hint.setAttribute('role','alert');}};actions.append(button);
    }
    root.append(fields,actions);video.src=url;
    return root;
}
