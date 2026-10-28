import {app} from '/scripts/app.js';
import {api} from '/scripts/api.js';
import {LOCAL_SLOTS,localKind,readLocalState,uploadLocalMedia,localTask,localMediaSpecs,localPickerEntries,resolveLocalPromptProfile} from './local_video_input_state.js';
import {hideNativeWidget,inputMediaUrl,attachCloudMediaPicker,createCloudRatioSelector,createCloudPromptHistory} from './gh_video_input_shared.js';
import {createPromptOptimizerController} from './prompt_optimizer_shared.js';
import {bindResponsiveDomHost,createCanvasPanelHost} from './responsive_dom_host.js';
import {videoInputStyles,createMediaCard} from './video_input_components.js';
import {connectedSpeechSource,projectDriverMedia,driverSlotChoices,connectedRoleSources,projectRoleMedia} from './local_driver_preview.js';
import {installStudioTheme as _installStudioTheme} from './studio_theme.js';
import {captureInputConnectionsByName,captureConfiguredInputConnectionsByName,mergeInputConnectionSnapshots,restoreInputConnectionsByName,missingStableInputs} from './dual_engine_input_links.js';
import {syncDualEngineSwitches,restoreDualEngineSwitches} from './dual_engine_switches.js';

const CONFIG = [['model_name','主模型'],['clip_name','CLIP 模型'],['video_vae_name','视频 VAE'],['audio_vae_name','音频 VAE'],['aspect','宽高比例'],['megapixels','百万像素'],['duration_seconds','时长（秒）']];
const DUAL_CONFIG = [
    ['fused_model_name','Fused 主模型','fused'],['hyperflow_base_model','HyperFlow Base','hyperflow'],
    ['hyperflow_weights','HyperFlow 权重','hyperflow'],['hyperflow_strength','强度','hyperflow'],
    ['strict_architecture','严格架构检查','hyperflow'],['clip_name','CLIP 模型','common'],
    ['video_vae_name','视频 VAE','common'],['audio_vae_name','音频 VAE','common'],
    ['aspect','宽高比例','common'],['megapixels','百万像素','common'],['duration_seconds','时长（秒）','common'],
    ['chunk_ffn_enabled','Chunk FFN','common'],['chunk_count','FFN 分块数','common'],['chunk_threshold','FFN 启用阈值','common'],
    ['sla_enabled','SLA','fused'],['sla_sparsity','SLA 稀疏率','fused'],['sla_block_size','SLA Block','fused'],
    ['sla_min_seq_len','SLA 序列阈值','fused'],['fused_steps','DualClock 步数','fused'],
    ['shift_video','Video Shift','fused'],['shift_audio','Audio Shift','fused']
];
const localElement=(tag,cls='',text='')=>{const item=document.createElement(tag);item.className=cls;item.textContent=text;return item;};
const localLabel=(en,zh)=>String(app.extensionManager?.setting?.get?.('Comfy.Locale')||navigator.language).startsWith('zh')?zh:en;
const pendingDualInputLinks=new WeakMap();

export function createLocalVideoPanel(node, apiClient=api) {
    const el=localElement,label=localLabel;
    const widget=name=>node.widgets?.find(w=>w.name===name),saved=widget('gh_local_state_json');
    const dual=Boolean(widget('engine_mode'));
    const configDefinition=dual?DUAL_CONFIG:CONFIG;
    const selectedModelName=()=>dual?(widget('engine_mode')?.value==='hyperflow'?controls.get('hyperflow_base_model')?.value:controls.get('fused_model_name')?.value):controls.get('model_name')?.value;
    let state=readLocalState(node.properties?.gh_local_video_state || saved?.value || '',{mode:widget('main_mode')?.value,prompt:widget('prompt')?.value});
    let restoring=true,persisting=false,disposed=false,optimizer=null,picker=null;
    const media=new Map(state.media),metadata=new Map(),pending=new Map(),controls=new Map();
    let driverAudio=null,driverRef='',driverRequest=null,driverMessage='',driverSignature='',preparingDriver=false;
    let roleSources=[];const roleAudios=new Map(),roleRequests=new Map();
    const driverSettings=()=>({family:widget('driver_model_family')?.value,policy:widget('driver_conflict')?.value,target:widget('driver_slot')?.value||'auto'});
    const roleProjection=()=>projectRoleMedia(state.mode,media,roleSources,roleAudios);
    // Both wiring families may stay connected. The active UI mode selects one:
    // keyframes use driver_audio; all-reference uses fixed role references.
    const usingRoles=()=>state.mode==='all_reference'&&roleSources.length>0;
    const driverProjection=()=>usingRoles()?roleProjection():projectDriverMedia(state.mode,media,metadata,driverSettings(),driverAudio,{preview:true});
    const effectiveMedia=()=>driverProjection().media;
    const root=el('div','gh-local-video-root');root.innerHTML=videoInputStyles+`<style>
      .gh-local-config{display:grid;gap:6px;margin-bottom:8px}.gh-local-config label{display:grid;grid-template-columns:86px minmax(0,1fr);gap:6px;align-items:center}
      .gh-local-config select,.gh-local-config input,.gh-local-driver select{box-sizing:border-box;min-width:0;width:100%;padding:6px;border:1px solid #385163;border-radius:5px;background:#101b24;color:#dce8ef;text-overflow:ellipsis}
      .gh-local-summary{display:block;width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;padding:7px;margin-bottom:7px;color:#8bdce7;background:#172b38;border:1px solid #385163;border-radius:5px}
      .gh-local-feedback{overflow-wrap:anywhere;margin:5px 0}.gh-local-video-root .gh-cloud-grid{grid-template-columns:repeat(auto-fit,minmax(min(120px,100%),1fr))}
      .gh-local-video-root .gh-cloud-meta{flex-wrap:wrap}.gh-local-video-root button{max-width:100%}
      .gh-local-driver{box-sizing:border-box;min-width:0;width:100%;margin:8px 0;padding:8px 10px;border:1px solid #385163;border-radius:7px;background:#142630}
      .gh-local-driver summary{cursor:pointer;color:#b9dbe8;font-weight:600}.gh-local-driver label{display:block;min-width:0}.gh-local-driver p{line-height:1.5;overflow-wrap:anywhere}
      .gh-local-driver-compatibility{color:#ffc45c}
      .gh-local-driver-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;min-width:0}
      .gh-local-driver-fields select{text-overflow:ellipsis}.gh-local-driver-fields label{overflow:hidden}
      .gh-local-video-root .gh-local-driver-help{display:inline-flex;align-items:center;justify-content:center;width:19px;height:19px;margin-left:7px;padding:0;border:1px solid #ef8080;border-radius:50%;background:#762f39;color:#ffe5e5;vertical-align:middle;font-weight:700;line-height:1}
    </style>`;
    const summary=el('button','gh-local-summary'),config=el('div','gh-local-config');
    const engineBar=el('div','gh-cloud-modes gh-local-engine');
    if(dual)for(const [value,text] of [['fused_turbo','Fused Turbo · 4-Step'],['hyperflow','HyperFlow · 8-Step']]){
        const button=el('button','',text);button.value=value;button.onclick=()=>changeConfig('engine_mode',value);engineBar.append(button);
    }
    summary.title='展开 / 折叠本地模型配置';summary.onclick=()=>{state.ui={models_collapsed:!state.ui?.models_collapsed};refreshSummary();persist();};
    const task=()=>localTask(state.mode,media);
    const ratio=createCloudRatioSelector({getTask:task,getMode:()=>state.mode,label,onChange:()=>changeConfig('aspect',ratio.button.value),
        adaptiveLabel:()=>task()==='l2v'?'跟随尾帧':['i2v','fl2v'].includes(task())?'跟随首帧':state.mode==='all_reference'?'自适应':'自适应 · 默认16:9'});
    for(const [name,title,scope='common'] of configDefinition) {
        const w=widget(name);let input;
        if(name==='aspect')input=ratio.button;
        else if(['megapixels','duration_seconds','hyperflow_strength','chunk_count','chunk_threshold','sla_sparsity','sla_min_seq_len','fused_steps','shift_video','shift_audio'].includes(name)) {
            input=el('input');input.type='number';input.min=w?.options?.min??'';input.max=w?.options?.max??'';input.step=w?.options?.step??1;
        } else if(['strict_architecture','chunk_ffn_enabled','sla_enabled'].includes(name)) {
            input=el('input');input.type='checkbox';input.checked=Boolean(w?.value);
        } else {
            input=el('select');const values=typeof w?.options?.values==='function'?w.options.values():w?.options?.values||[];
            for(const value of values)input.append(new Option(value,value));
        }
        if(input.type!=='checkbox')input.value=w?.value??(name==='megapixels'?0.5:name==='duration_seconds'?5:'adaptive');
        input.title=String(input.type==='checkbox'?input.checked:input.value);input.setAttribute('aria-label',title);input.dataset.config=name;
        if(name!=='aspect')input.onchange=()=>changeConfig(name,input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value);
        controls.set(name,input);const row=el('label');row.dataset.engineScope=scope;row.append(el('span','',title),input);config.append(row);
    }
    const modes=el('div','gh-cloud-modes');
    for(const [value,text] of [['text_keyframes','文本 / 首尾帧'],['all_reference','全能参考']]) {
        const button=el('button','',text);button.value=value;
        button.onclick=()=>{
            if(state.mode!==value){
                const family=widget('driver_model_family');
                if(family&&family.value!=='unconfirmed'&&family.value!==(value==='all_reference'?'Ref2VA':'FL2VA'))family.value='unconfirmed';
                const slot=widget('driver_slot');
                if(slot&&!driverSlotChoices(value,slot.value,media).selected)slot.value='auto';
            }
            state.mode=value;if(widget('main_mode'))widget('main_mode').value=value;changed();render();
        };modes.append(button);
    }
    const prompt=el('textarea','gh-cloud-prompt');prompt.value=state.prompt;prompt.setAttribute('aria-label','Local Prompt');
    const history=createCloudPromptHistory({textarea:prompt,label,initialState:state.optimizer||{},onApply:value=>{prompt.value=value;changed();}});
    const groups=el('div','gh-local-media'),feedback=el('div','gh-local-feedback');feedback.setAttribute('role','status');
    root.append(summary,...(dual?[engineBar]:[]),config,modes,history.element,groups,feedback);
    const driver=el('details','gh-local-driver'),driverControls=new Map();
    const driverHeading=el('summary','','连接口播 AUDIO（可选）');driver.append(driverHeading);
    const driverHelp=el('button','gh-local-driver-help','?');driverHelp.type='button';driverHelp.setAttribute('aria-label','口播连接与时长说明');driverHeading.append(driverHelp);
    const driverTip=el('div','gh-local-driver-tooltip','将口播 AUDIO 接入 driver_audio。未连接时保持原行为；连接后按实际音频时长向上匹配，最多 345 帧 / 14.375s，不截断台词。模型家族需您明确确认，口型效果仍需实机验收。');
    driverTip.setAttribute('role','tooltip');driverTip.hidden=true;driverTip.style.cssText='position:fixed;z-index:100000;box-sizing:border-box;padding:10px 12px;border:1px solid #a3606a;border-radius:7px;background:#192b36;color:#e6f0f5;font:13px/1.6 sans-serif;overflow-wrap:anywhere;pointer-events:none;box-shadow:0 4px 16px #0008';document.body.append(driverTip);
    const closeDriverTip=()=>{driverTip.hidden=true;};
    const openDriverTip=()=>{
        driverTip.hidden=false;const r=driverHelp.getBoundingClientRect(),bounds=root.getBoundingClientRect();
        const width=Math.max(100,Math.min(320,bounds.width-16,window.innerWidth-16));driverTip.style.width=width+'px';
        driverTip.style.left=Math.max(8,bounds.left,Math.min(r.left,bounds.right-width,window.innerWidth-width-8))+'px';
        const height=driverTip.getBoundingClientRect().height;driverTip.style.top=Math.max(8,r.bottom+6+height>window.innerHeight?r.top-height-6:r.bottom+6)+'px';
    };
    driverHelp.addEventListener('mouseenter',openDriverTip);driverHelp.addEventListener('mouseleave',closeDriverTip);driverHelp.addEventListener('focus',openDriverTip);driverHelp.addEventListener('blur',closeDriverTip);
    driverHelp.addEventListener('click',e=>{e.preventDefault();openDriverTip();});driverHelp.addEventListener('keydown',e=>{if(e.key==='Escape')closeDriverTip();});root.addEventListener('scroll',closeDriverTip);
    const driverStatus=el('p','gh-local-driver-status');driverStatus.setAttribute('role','status');driver.append(driverStatus);
    const driverCompatibility=el('p','gh-local-driver-compatibility');driverCompatibility.setAttribute('role','status');driver.append(driverCompatibility);
    const driverFields=el('div','gh-local-driver-fields');driver.append(driverFields);
    for(const [name,title,options] of [
        ['driver_model_family','模型家族',[['unconfirmed','未确认（连接后拒绝执行）'],['FL2VA','FL2VA · 首帧/首尾帧'],['Ref2VA','Ref2VA · 全能参考']]],
        ['driver_conflict','已有音频',[['reject_conflicts','有冲突时拒绝'],['use_connected_audio','明确使用连接口播作为驱动']]],
        ['driver_slot','口播槽位',[['auto','自动追加（保持原编号）'],['hybrid_audio','Hybrid 音频'],['ref_audio_1','参考音频槽 1'],['ref_audio_2','参考音频槽 2'],['ref_audio_3','参考音频槽 3']]]
    ]){
        const row=el('label'),select=el('select');select.dataset.driver=name;select.style.cssText='width:100%;min-width:0;box-sizing:border-box;margin:5px 0;padding:6px';
        for(const [value,text] of options)select.append(new Option(text,value));
        select.value=widget(name)?.value||options[0][0];select.onchange=()=>{if(widget(name))widget(name).value=select.value;changed();render();};
        row.append(el('span','',title),select);driverFields.append(row);driverControls.set(name,select);hideNativeWidget(widget(name));
    }
    modes.after(driver);
    const rolesStatus=el('p','gh-local-role-status');rolesStatus.setAttribute('role','status');driver.after(rolesStatus);
    rolesStatus.title='连接多角色 A/B/C 到 reference_audio_1/2/3；三路为参考音频，不自动拼接，不锁定三条声轨。独立音频补齐视频时长后累计最多 15 秒，三路请先用 4 秒视频测试。';
    function refreshDriverControls() {
        const expected=state.mode==='all_reference'?'Ref2VA':'FL2VA';
        const family=driverControls.get('driver_model_family'),value=widget('driver_model_family')?.value||'unconfirmed';
        family.replaceChildren(new Option('未确认（请确认所选主模型）','unconfirmed'),new Option(expected==='FL2VA'?'FL2VA · 首帧/首尾帧':'Ref2VA · 全能参考',expected));
        if(!['unconfirmed',expected].includes(value)){
            const old=new Option('当前设置不匹配，请重新确认',value);old.hidden=true;old.disabled=true;family.append(old);
        }
        family.value=value;
        const slot=driverControls.get('driver_slot'),target=widget('driver_slot')?.value||'auto';
        const choices=driverSlotChoices(state.mode,target,media);
        slot.replaceChildren(...choices.options.map(([v,t])=>new Option(t,v)));
        if(!choices.selected){const empty=new Option('请选择可用槽位或明确替换已有音频','');empty.hidden=true;empty.disabled=true;slot.append(empty);}
        slot.value=choices.selected;
        slot.title=choices.automatic?'当前为自动定位；手动选择后固定到该槽位。':'已明确选择口播槽位';
        const filename=String(selectedModelName()||'').replaceAll('\\','/').split('/').pop().toLowerCase();
        const known=filename.startsWith('minimax_h3_fl2va_')?'FL2VA':filename.startsWith('minimax_h3_ref2va_')?'Ref2VA':null;
        driverCompatibility.textContent=known&&known!==expected?`当前主模型属于 ${known}，与此模式不匹配；请在上方切换为 ${expected} 主模型。`:
            value==='unconfirmed'?'请确认上方主模型支持当前模式，再选择口播模型家族。':value!==expected?'保存的口播模型家族与当前模式不匹配，请重新确认。':'';
        driverCompatibility.hidden=!driverCompatibility.textContent;
    }
    async function syncDriver() {
        roleSources=connectedRoleSources(node);
        const refs=new Set(roleSources.map(s=>s.ref).filter(Boolean));
        for(const ref of roleAudios.keys())if(!refs.has(ref))roleAudios.delete(ref);
        await Promise.all([...refs].map(ref=>{
            if(roleAudios.has(ref))return;
            if(!roleRequests.has(ref))roleRequests.set(ref,(async()=>{
                try{const response=await apiClient.fetchApi(`/hutx/minimax-h3/speech/adopted-preview?file=${encodeURIComponent(ref)}`,{cache:'no-store'});
                    if(!response.ok)throw Error();const data=await response.json();
                    if(!/^hutx-speech\/adopted\/[a-f0-9]{64}\.wav$/.test(data.audio_file)||!Number.isFinite(data.duration_seconds)||data.duration_seconds<=0)throw Error();
                    if(!disposed&&roleSources.some(s=>s.ref===ref))roleAudios.set(ref,data);
                }catch{}finally{roleRequests.delete(ref);}
            })());return roleRequests.get(ref);
        }));
        const source=connectedSpeechSource(node),ref=source.ref||'';
        if(ref!==driverRef) {
            driverRef=ref;driverAudio=null;driverMessage=source.message||'正在读取已采用口播…';
            driverRequest=ref?(async()=>{
                try {
                    const response=await apiClient.fetchApi(`/hutx/minimax-h3/speech/adopted-preview?file=${encodeURIComponent(ref)}`,{cache:'no-store'});
                    if(!response.ok)throw new Error();
                    const data=await response.json();
                    if(!/^hutx-speech\/adopted\/[a-f0-9]{64}\.wav$/.test(data.audio_file)||!Number.isFinite(data.duration_seconds)||data.duration_seconds<=0)throw new Error();
                    if(!disposed&&driverRef===ref){driverAudio=data;driverMessage='';}
                }catch {if(!disposed&&driverRef===ref)driverMessage='已采用口播不可用，请重新试听并采用。';}
            })():null;
        }else if(!ref)driverMessage=source.message;
        const update=()=>{
            if(disposed)return;
            const signature=JSON.stringify([driverRef,driverAudio,driverMessage,driverSettings(),roleSources,[...roleAudios]]);
            if(signature!==driverSignature){const prior=driverSignature;driverSignature=signature;if(prior&&!preparingDriver)optimizer?.invalidate();render();}
        };
        update();await driverRequest;update();
    }
    function show(message,error=false){feedback.textContent=message;feedback.style.color=error?'#ff9898':'#9acbd5';}
    function persist() {
        if(restoring||persisting||disposed)return;
        persisting=true;
        try {
        state=readLocalState({...state,prompt:prompt.value,media:[...media],optimizer:optimizer.stateForSerialization()});
        const text=JSON.stringify(state);if(new Blob([text]).size>1048576)throw new Error('Local state exceeds 1 MiB');
        if(saved)saved.value=text;node.properties||={};node.properties.gh_local_video_state=text;
        if(widget('prompt'))widget('prompt').value=state.prompt;
        if(widget('main_mode'))widget('main_mode').value=state.mode;
        for(const slot of LOCAL_SLOTS)if(widget(slot))widget(slot).value=media.get(slot)?.name||'';
        } finally {persisting=false;}
    }
    function changed(){if(restoring||persisting||disposed)return;optimizer?.invalidate();persist();picker?.refresh();}
    function changeConfig(name,value) {
        const snapshot=dual&&name==='engine_mode'?captureInputConnectionsByName(node,node.graph||app.graph):null;
        const w=widget(name);if(w)w.value=value;
        if(snapshot){
            const result=restoreInputConnectionsByName(node,snapshot,node.graph||app.graph);
            if(result.pending.size)pendingDualInputLinks.set(node,result.pending);
        }
        if(dual&&name==='engine_mode')syncDualEngineSwitches(node,value);
        controls.get(name)?.setAttribute('title',String(value));changed();refreshSummary();if(['model_name','fused_model_name','hyperflow_base_model','engine_mode'].includes(name))refreshDriverControls();
    }
    function refreshEngineVisibility(){
        if(!dual)return;
        const mode=widget('engine_mode')?.value||'fused_turbo',scope=mode==='hyperflow'?'hyperflow':'fused';
        for(const row of config.children)row.hidden=!['common',scope].includes(row.dataset.engineScope);
        for(const button of engineBar.children)button.className=button.value===mode?'active':'';
    }
    function refreshSummary() {
        const aspect=controls.get('aspect').value,mp=Number(controls.get('megapixels').value),seconds=Number(controls.get('duration_seconds').value);
        const visual=state.mode==='all_reference'?LOCAL_SLOTS.filter(s=>s.startsWith('ref_video_')||s.startsWith('ref_image_')).sort((a,b)=>Number(b.startsWith('ref_video_'))-Number(a.startsWith('ref_video_'))).find(s=>media.has(s)):['first_frame','last_frame'].find(s=>media.has(s));
        const dims=metadata.get(media.get(visual)?.name);
        const [a,b]=(aspect==='adaptive'?'16:9':aspect).split(':').map(Number);
        const r=aspect==='adaptive'&&dims?.width&&dims?.height?dims.width/dims.height:a/b;
        const align=v=>Math.min(16384,Math.max(32,Math.floor(v/32+0.5)*32));
        const width=align(Math.sqrt(mp*1024*1024*r)),height=align(Math.sqrt(mp*1024*1024/r));
        const frames=Math.round(seconds*24)+(5-Math.round(seconds*24)%17+17)%17;
        const engine=dual?(widget('engine_mode')?.value==='hyperflow'?'HyperFlow · 8-Step':'Fused Turbo')+' · ':'';
        const text=`${state.ui?.models_collapsed?'▸':'▾'} ${engine}${selectedModelName()} · ${width}×${height}${aspect==='adaptive'&&visual&&!dims?'（等待素材尺寸）':''} · ${seconds}s / ${frames}帧`;
        summary.textContent=text;summary.title=text;config.hidden=Boolean(state.ui?.models_collapsed);refreshEngineVisibility();ratio.refresh();
    }
    async function inspect(name) {
        if(metadata.has(name))return metadata.get(name);
        if(!pending.has(name))pending.set(name,(async()=>{
            const response=await apiClient.fetchApi(`/api/hutx/minimax-h3/local-media-info?name=${encodeURIComponent(name)}`,{cache:'no-store'});
            if(!response.ok)throw new Error('无法读取本地素材信息，请重新选择素材。');
            const data=await response.json();metadata.set(name,data);return data;
        })().finally(()=>pending.delete(name)));
        return pending.get(name);
    }
    async function inspectActive() {
        const priorSlot=driverProjection().slot;
        const names=[...media].filter(([slot])=>localKind(slot)!=='audio'&&slot.startsWith('ref_')===(state.mode==='all_reference')).map(([,entry])=>entry.name);
        await Promise.all(names.map(inspect));
        if(!disposed){refreshSummary();picker?.refresh();if(priorSlot!==driverProjection().slot)render();}
    }
    async function chooseFile(slot,droppedFile=null) {
        let file=droppedFile;
        if(!file)file=await new Promise(resolve=>{const input=el('input');input.type='file';input.accept=localKind(slot)+'/*';input.onchange=()=>resolve(input.files?.[0]);input.oncancel=()=>resolve(null);input.click();});
        if(!file)return;
        show('正在上传…');
        try {
            const name=await uploadLocalMedia(apiClient,file);if(disposed)return;
            metadata.delete(name);media.set(slot,{name,kind:localKind(slot)});changed();render();
            await inspectActive();show('素材已配置。');
        }catch(error){show(error.message,true);}
    }
    function insertTag(tag){if(!tag)return;prompt.setRangeText(tag,prompt.selectionStart,prompt.selectionEnd,'end');changed();prompt.focus();}
    function render() {
        refreshDriverControls();
        const projection=driverProjection(),visibleMedia=projection.media;
        driver.hidden=usingRoles();
        rolesStatus.hidden=!usingRoles();rolesStatus.textContent=usingRoles()?projection.message:'';
        driverStatus.textContent=projection.message||driverMessage||connectedSpeechSource(node).message||'';
        groups.replaceChildren();
        for(const button of modes.children)button.className=button.value===state.mode?'active':'';
        const slots=LOCAL_SLOTS.filter(s=>s.startsWith('ref_')===(state.mode==='all_reference'));
        for(const kind of ['image','video','audio']) {
            const selected=slots.filter(s=>localKind(s)===kind);if(!selected.length)continue;
            const section=el('section','gh-cloud-section'),grid=el('div','gh-cloud-grid');
            section.append(el('div','gh-cloud-section-title',kind==='image'?'图片 / 关键帧':kind==='video'?'参考视频':'音频'),grid);
            for(const slot of selected) {
                const card=createMediaCard({slot,entry:visibleMedia.get(slot),kind,label,url:visibleMedia.get(slot)?inputMediaUrl(apiClient,visibleMedia.get(slot).name):'',
                    getTag:()=>localMediaSpecs(state.mode,effectiveMedia(),metadata,{ignoreVideoAudio:usingRoles()}).find(s=>s.slot===slot&&s.kind===kind)?.label||'',chooseFile,insertTag,
                    removeMedia:()=>{media.delete(slot);changed();render();},onUpdate:()=>{changed();picker?.refresh();},trimStartField:'trimStart',trimEndField:'trimEnd',muteLabel:'忽略参考视频原声'});
                if(slot===projection.slot||projection.slots?.includes(slot)){
                    card.dataset.connectedAudio='true';card.querySelector('.gh-cloud-remove')?.remove();card.querySelector('.gh-cloud-meta')?.remove();
                    const name=card.querySelector('.gh-cloud-file');if(name){name.textContent=projection.slots?.includes(slot)?`${roleSources.find(s=>s.slot===slot)?.name} · 已采用`:'已采用口播 · driver_audio';name.title='来自连接的口播节点；修改音频请在上游重新生成并采用。';}
                }
                card.dataset.slot=slot;grid.append(card);
            }
            groups.append(section);
        }
        refreshSummary();picker?.refresh();inspectActive().catch(error=>show(error.message,true));node.setDirtyCanvas?.(true,true);
    }
    optimizer=createPromptOptimizerController({node,app,api:apiClient,label,initialState:state.optimizer||{},
        getPrompt:()=>prompt.value,getTask:task,getDuration:()=>controls.get('duration_seconds').value,getMedia:effectiveMedia,inputMediaUrl,
        supportedTasks:['t2v','i2v','l2v','fl2v','ref2v'],tagContract:'local_h3_v1',resolveProfile:resolveLocalPromptProfile,blockQueueOnFailure:true,
        payloadTask:task=>state.mode==='text_keyframes'&&effectiveMedia().has('hybrid_audio')?'HYBRID':({t2v:'T2VA',i2v:'I2VA',l2v:'L2VA',fl2v:'FL2VA',ref2v:'Ref2VA'})[task],
        prepareMedia:async()=>{preparingDriver=true;try{await inspectActive();await syncDriver();if(usingRoles()){const checked=roleProjection();if(checked.error)throw new Error(checked.message);}else{const checked=projectDriverMedia(state.mode,media,metadata,driverSettings(),driverAudio);if(driverRef&&!checked.slot)throw new Error(checked.message||driverMessage);}}finally{preparingDriver=false;}},
        mediaSpecs:()=>localMediaSpecs(state.mode,effectiveMedia(),metadata,{ignoreVideoAudio:usingRoles()}),
        setPrompt:value=>{history.record(optimizer.stateForSerialization().original_prompt,value);prompt.value=value;persist();},onStateChange:persist});
    history.element.after(optimizer.element);
    picker=attachCloudMediaPicker({textarea:prompt,getMode:()=>state.mode,getMedia:effectiveMedia,label,onChange:changed,getEntries:()=>localPickerEntries(state.mode,effectiveMedia(),metadata,{ignoreVideoAudio:usingRoles()}).map(entry=>{
        const role=roleSources.find(s=>entry.slot===s.slot+':audio');
        if(role)return {...entry,filename:role.name,name:entry.name+' · '+role.name};
        return entry.slot===driverProjection().slot+':audio'?{...entry,filename:'已采用口播',name:entry.name+' · 已采用口播'}:entry;
    })});
    prompt.addEventListener('input',changed);
    for(const name of [...configDefinition.map(([name])=>name),...(dual?['engine_mode']:[]),'main_mode','prompt',...LOCAL_SLOTS,'gh_local_state_json'])hideNativeWidget(widget(name));
    for(const name of ['main_mode','prompt']) {
        const w=widget(name);if(w){const prior=w.callback;w.callback=function(...args){if(restoring||persisting||disposed)return;prior?.apply(this,args);if(name==='prompt')prompt.value=w.value;else state.mode=w.value;changed();render();};}
    }
    function hydrate(raw) {
        const next=readLocalState(raw,{mode:widget('main_mode')?.value,prompt:widget('prompt')?.value});
        restoring=true;optimizer.cancel();state=next;media.clear();for(const entry of state.media)media.set(...entry);
        prompt.value=state.prompt;history.hydrate(state.optimizer||{});optimizer.restore(state.optimizer||{});
        for(const [name,input] of controls)if(widget(name)){if(input.type==='checkbox')input.checked=Boolean(widget(name).value);else input.value=widget(name).value;}
        for(const [name,input] of driverControls)if(widget(name))input.value=widget(name).value;
        restoring=false;persist();render();
    }
    const configure=node.onConfigure;node.onConfigure=function(info){
        const graph=this.graph||app.graph;
        const snapshot=dual?mergeInputConnectionSnapshots(
            captureConfiguredInputConnectionsByName(info,graph),captureInputConnectionsByName(this,graph)):null;
        const result=configure?.apply(this,arguments);
        if(snapshot){
            const outcome=restoreInputConnectionsByName(this,snapshot,graph);
            if(outcome.pending.size)pendingDualInputLinks.set(this,outcome.pending);else pendingDualInputLinks.delete(this);
        }
        hydrate(info?.properties?.gh_local_video_state||saved?.value||'');return result;
    };
    const serialize=node.onSerialize;node.onSerialize=function(){persist();return serialize?.apply(this,arguments);};
    const executed=node.onExecuted;node.onExecuted=function(message){executed?.apply(this,arguments);if(message?.local_report?.[0])try{const r=JSON.parse(message.local_report[0]);show(`${r.task.toUpperCase()} · ${r.width}×${r.height} · ${r.frame_count}帧 · ${r.actual_seconds.toFixed(3)}s · ${r.fps}fps`+(r.driver_audio?` · 已锁定连接口播 ${r.driver_audio.source_seconds.toFixed(3)}s · ${r.driver_audio.slot}`:''));}catch{show('实际画布信息请查看 local_report。');}};
    if(saved)saved.serializeValue=()=>{persist();return saved.value;};
    const canvasHost=createCanvasPanelHost(root);
    const dom=node.addDOMWidget('gh_local_video_panel','gh_local_video_panel',canvasHost,{serialize:false});
    let responsive=null;
    if(dom){dom.options||={};dom.options.getMinHeight=()=>500;responsive=bindResponsiveDomHost(node,dom,canvasHost,()=>{picker.refresh();ratio.refresh();},root);}
    const driverPoll=setInterval(()=>{syncDriver().catch(()=>{});},500);
    const removed=node.onRemoved;node.onRemoved=function(){disposed=true;driverTip.remove();clearInterval(driverPoll);optimizer.destroy();picker.destroy();ratio.destroy();responsive?.destroy();return removed?.apply(this,arguments);};
    node.setSize?.([Math.max(460,node.size?.[0]||460),Math.max(900,node.size?.[1]||900)]);
    hydrate(state);
    syncDriver().catch(()=>{});
    return {element:root,canvasHost,optimizer,prompt,controls,chooseFile,ready:inspectActive,serialize:()=>{persist();return JSON.parse(saved?.value||JSON.stringify(state));}};
}

app.registerExtension({name:'HuTX.MiniMaxH3Studio.LocalVideoInput',beforeRegisterNodeDef(nodeType,nodeData){
    if(!['GHLocalVideoInputGH','GHLocalVideoInputDualEngineGH'].includes(nodeData.name))return;
    const created=nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated=function(){const result=created?.apply(this,arguments);this.hutxWorkbenchPanel=createLocalVideoPanel(this);return result;};
},loadedGraphNode(node){
    if(node?.type!=='GHLocalVideoInputDualEngineGH')return;
    const missing=missingStableInputs(node);
    if(missing.length)console.warn(`[HuTX DualEngine] skipped missing input: ${missing.join(', ')}`);
    const snapshot=pendingDualInputLinks.get(node);
    if(snapshot){
        const outcome=restoreInputConnectionsByName(node,snapshot,node.graph||app.graph,{warn:true});
        if(outcome.pending.size)pendingDualInputLinks.set(node,outcome.pending);else pendingDualInputLinks.delete(node);
    }
    // Run after all nodes and links in a saved workflow have been configured.
    setTimeout(()=>restoreDualEngineSwitches(node,node.widgets?.find(widget=>widget.name==='engine_mode')?.value||'fused_turbo'),0);
}});
