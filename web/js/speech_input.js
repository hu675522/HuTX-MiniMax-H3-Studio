import { app } from '/scripts/app.js';
import { api } from '/scripts/api.js';
import { bindResponsiveDomHost,createCanvasPanelHost } from './responsive_dom_host.js';
import { createSpeechController } from './speech_controller.js';
import {installStudioTheme as _installStudioTheme} from './studio_theme.js';

const SPEECH_FIELDS=['engine','mode','text','reference_text','reference_file','voice','speed','mock_demo','revision','cloud_model','workspace','adopted_audio_file'];
const SPEECH_ROUTE='/hutx/minimax-h3/speech';

export function createSpeechPanel(node, {embedded=false,onState=()=>{}}={}) {
    const root=document.createElement('div');root.className='hutx-speech-root';
    root.classList.add(embedded?'hutx-embedded-speech':'hutx-single-speech');
    if(!document.getElementById('hutx-speech-style')) {
        const style=document.createElement('style');style.id='hutx-speech-style';style.textContent=`
        .hutx-speech-root{width:100%;max-width:none;min-width:0;box-sizing:border-box;align-self:stretch;padding:10px;background:#12212b;color:#dfedf2;font:13px sans-serif;overflow:auto}
        .hutx-speech-root *{box-sizing:border-box;min-width:0}
        .hutx-speech-root label{display:flex;flex-direction:column;gap:6px;margin:12px 0;overflow-wrap:anywhere;line-height:1.5}
        .hutx-speech-root label:has(input[type=checkbox]){flex-direction:row;align-items:center;gap:8px}
        .hutx-speech-root input[type=checkbox]{order:-1;flex:0 0 auto;margin:0;width:16px;height:16px;accent-color:#39b9c9}
        .hutx-speech-root textarea,.hutx-speech-root select,.hutx-speech-root input:not([type=checkbox]),.hutx-speech-root audio{display:block;width:100%;max-width:100%;margin-top:4px}
        .hutx-speech-root textarea,.hutx-speech-root select,.hutx-speech-root input{background:#192f3b;color:#dfedf2;border:1px solid #3e6173;border-radius:5px;padding:6px}
        .hutx-speech-root textarea{height:96px;resize:vertical;line-height:1.6}
        .hutx-speech-root select,.hutx-speech-root input:not([type=checkbox]){min-height:34px}
        .hutx-speech-root strong{display:block;font-size:14px;line-height:1.6}
        .hutx-speech-root p{line-height:1.65;margin:10px 0}
        .hutx-speech-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:8px 0}
        .hutx-speech-root button,.hutx-speech-root a{padding:6px;background:#244655;border:1px solid #426b7b;border-radius:5px;color:#dff5ff;cursor:pointer;text-decoration:none}
        .hutx-speech-root button:disabled{opacity:.45;cursor:default}
        .hutx-speech-row button{min-height:34px;line-height:1.4;padding:7px 12px}
        .hutx-speech-row.hutx-speech-actions{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:start;gap:8px}
        .hutx-speech-action-controls{display:flex;align-items:center;flex-wrap:wrap;gap:6px;min-width:0}
        .hutx-speech-actions .hutx-speech-action-controls button{padding:6px 8px;font-size:12px}
        .hutx-speech-root .hutx-speech-actions label{display:flex;flex-direction:row;align-items:center;gap:8px;margin:0;flex:0 0 auto}
        .hutx-speech-root .hutx-speech-actions input{width:52px;margin:0;min-height:34px}
        .hutx-speech-result-heading{display:flex;align-items:center;gap:4px}
        .hutx-speech-root input[type=file]{padding:8px}
        .hutx-speech-root input[type=file]::file-selector-button{background:#244655;color:#dfedf2;border:0;border-radius:4px;padding:6px 10px;margin-right:8px}
        .hutx-speech-notice{color:#ffc45c;overflow-wrap:anywhere}
        .hutx-speech-status{overflow-wrap:anywhere;white-space:pre-wrap;margin:8px 0}
        .hutx-speech-root [hidden]{display:none!important}
        .hutx-speech-root details{overflow-wrap:anywhere;margin:14px 0;padding:10px;border:1px solid #304c5a;border-radius:7px;background:#142833}
        .hutx-speech-root summary{cursor:pointer;line-height:1.6;font-weight:600}
        .hutx-speech-target{display:grid;grid-template-columns:110px minmax(0,1fr);gap:10px;padding:9px 0;border-bottom:1px solid #29414e;line-height:1.6}
        .hutx-speech-target:last-child{border-bottom:0}
        .hutx-speech-target span:first-child{color:#8dd8e5;font-weight:600}
        .hutx-speech-target small{display:block;color:#96aebb;font-size:11px;font-weight:400;margin-top:3px}
        .hutx-speech-reference{margin:12px 0;padding:12px;border:1px dashed #426b7b;border-radius:8px;background:#142833}
        .hutx-speech-reference .hutx-speech-row{margin-bottom:0}
        .hutx-speech-reference audio{margin:10px 0}
        .hutx-speech-reference-header{display:flex;align-items:center;gap:8px;min-width:0}
        .hutx-speech-reference-header input{flex:1;margin-top:0!important;width:0!important}
        .hutx-speech-reference-actions{display:flex;align-items:center;gap:6px;flex:0 0 auto}
        .hutx-speech-root .hutx-speech-reference-actions button{min-height:30px;padding:5px 9px;background:transparent;border-color:#426b7b}
        .hutx-speech-root .hutx-speech-reference-actions button[data-icon=true]{width:30px;height:30px;padding:0;font-size:20px;line-height:1}
        .hutx-speech-root .hutx-speech-reference-actions button:hover{background:#244655;border-color:#8bdce7}
        .hutx-speech-result{margin:12px 0;padding:12px;border:1px solid #426b7b;border-radius:8px;background:#142833}
        .hutx-speech-result-header{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px}
        .hutx-speech-result-header a{display:inline-flex;align-items:center;padding:6px 10px;line-height:1.4}
        .hutx-speech-result audio{height:40px;margin:0;color-scheme:dark}
        .hutx-speech-heading{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
        .hutx-speech-root .hutx-speech-help{display:inline-flex;align-items:center;justify-content:center;width:19px;height:19px;padding:0;border:1px solid #ef8080;border-radius:50%;background:#762f39;color:#ffe5e5;font-size:12px;font-weight:700;line-height:1;flex:0 0 auto;vertical-align:middle;margin-left:6px}
        .hutx-speech-tooltip{position:fixed;z-index:100000;box-sizing:border-box;padding:10px 12px;border:1px solid #a3606a;border-radius:7px;background:#192b36;color:#e6f0f5;font:13px/1.6 sans-serif;overflow-wrap:anywhere;white-space:pre-wrap;pointer-events:none;box-shadow:0 4px 16px #0008}
        .hutx-speech-root .hutx-speech-adopt{background:#35434c;border-color:#65747e;color:#d8e0e5}
        .hutx-speech-root .hutx-speech-adopt[data-adopted=true]{background:#205b43;border-color:#5fc993;color:#bcf8d7;opacity:1}
        .hutx-speech-root .hutx-speech-adopt[data-ready=true]{background:#94601b;border-color:#ffc666;color:#fff1cf;box-shadow:0 0 0 1px #ffc66655}
        .hutx-speech-timing{margin:0;min-height:34px;display:flex;align-items:center;white-space:nowrap;font-size:12px;line-height:1.5}
        .hutx-speech-status:empty{display:none}
        `;document.head.append(style);
    }
    const tooltip=document.createElement('div');tooltip.className='hutx-speech-tooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;document.body.append(tooltip);
    function help(label,message=''){
        const b=document.createElement('button');b.className='hutx-speech-help';b.type='button';b.textContent='?';b.setAttribute('aria-label',label);
        b.helpText=message;
        const close=()=>{tooltip.hidden=true;};
        const open=()=>{
            tooltip.textContent=b.helpText;tooltip.hidden=false;
            const r=b.getBoundingClientRect(),bounds=root.getBoundingClientRect();
            const width=Math.max(100,Math.min(320,bounds.width-16,window.innerWidth-16));tooltip.style.width=width+'px';
            const left=Math.max(8,bounds.left,Math.min(r.left,bounds.right-width,window.innerWidth-width-8));
            const height=tooltip.getBoundingClientRect().height;
            tooltip.style.left=left+'px';tooltip.style.top=Math.max(8,r.bottom+6+height>window.innerHeight?r.top-height-6:r.bottom+6)+'px';
        };
        b.addEventListener('mouseenter',open);b.addEventListener('mouseleave',close);b.addEventListener('focus',open);b.addEventListener('blur',close);
        b.addEventListener('click',open);b.addEventListener('keydown',e=>{if(e.key==='Escape')close();});return b;
    }
    root.addEventListener('scroll',()=>{tooltip.hidden=true;});
    const heading=document.createElement('div');heading.className='hutx-speech-heading';root.append(heading);
    const title=document.createElement('strong');title.textContent='口播音频生成 · 本地 / 云端';heading.append(title);
    const notice=help('运行环境与云端使用说明','正在检查本地运行环境。云端生成会上传参考录音与台词，并可能计费；不会自动跨端回退。');heading.append(notice);
    const controls={},labels={};
    function field(name,label,type,options=[]) {
        const wrap=document.createElement('label');wrap.append(document.createTextNode(label));
        const el=document.createElement(type==='select'?'select':type==='textarea'?'textarea':'input');
        if(el.tagName==='INPUT')el.type=type;
        el.dataset.field=name;
        for(const [value,text] of options){const option=document.createElement('option');option.value=value;option.textContent=text;el.append(option);}
        wrap.append(el);root.append(wrap);controls[name]=el;labels[name]=wrap;return el;
    }
    field('engine','执行端','select',[['local','本地 · CosyVoice 3'],['cloud','云端 · 百炼北京']]);
    field('cloud_model','云端模型（预设音色建议自动选择）','select',[
        ['auto','自动选择'],['cosyvoice-v3.5-plus','CosyVoice v3.5 Plus（克隆）'],['cosyvoice-v3.5-flash','CosyVoice v3.5 Flash（克隆）'],['cosyvoice-v3-flash','CosyVoice v3 Flash（系统音色）'],['qwen-audio-3.1-tts-flash','Qwen-Audio 3.1 Flash（多语种系统音色）']]);
    field('workspace','百炼业务空间 ID（可选；留空使用官方兼容域名）','text');
    const cloudUploadInfo=document.createElement('p');cloudUploadInfo.className='hutx-speech-notice';root.append(cloudUploadInfo);
    field('mode','音色方式','select',[['clone','参考声线'],['preset','预设音色']]);
    field('reference_file','参考音频：input 内 PCM16 WAV 相对路径','text');
    const upload=document.createElement('input');upload.type='file';upload.accept='.wav';upload.title='上传参考 WAV 到本机 ComfyUI';root.append(upload);
    const referenceCard=document.createElement('div');referenceCard.className='hutx-speech-reference';root.append(referenceCard);
    const referenceHeader=document.createElement('div');referenceHeader.className='hutx-speech-reference-header';referenceCard.append(referenceHeader);
    const referenceName=document.createElement('input');referenceName.setAttribute('aria-label','参考音频名称');referenceName.placeholder='音频名称（可修改）';referenceName.maxLength=120;referenceHeader.append(referenceName);
    const referencePlayer=document.createElement('audio');referencePlayer.controls=true;referencePlayer.preload='metadata';referenceCard.append(referencePlayer);
    const referenceActions=document.createElement('div');referenceActions.className='hutx-speech-reference-actions';referenceHeader.append(referenceActions);
    const chooseReference=document.createElement('button');chooseReference.textContent='上传参考音频';chooseReference.onclick=()=>upload.click();referenceActions.append(chooseReference);
    const removeReference=document.createElement('button');removeReference.textContent='×';removeReference.dataset.icon='true';removeReference.setAttribute('aria-label','移除音频');removeReference.title='移除音频（不删除磁盘文件）';referenceActions.append(removeReference);
    referenceName.onchange=()=>{node.properties||={};node.properties.hutx_speech_reference_name=referenceName.value.trim().slice(0,120);node.setDirtyCanvas?.(true,true);};
    removeReference.onclick=()=>{referencePlayer.pause();controls.reference_file.value='';controls.reference_text.value='';if(node.properties)delete node.properties.hutx_speech_reference_name;setWidget('adopted_audio_file','');persist();controller.invalidate();renderReference();};
    field('reference_text','参考录音原文（不是新台词）','textarea');
    field('voice','预设音色（按执行端提供）','select');
    field('text','新台词（与视频画面描述分开）','textarea');
    const speed=field('speed','语速','number');speed.min='0.5';speed.max='2';speed.step='0.1';
    field('mock_demo','明确开启 Mock 测试音模式','checkbox');
    const voiceName=document.createElement('input');voiceName.placeholder='保存为本机音色的名称';voiceName.maxLength=80;root.append(voiceName);
    const saveVoice=document.createElement('button');saveVoice.textContent='将当前参考录音保存为本机音色';root.append(saveVoice);
    const credentialPanel=document.createElement('details');credentialPanel.innerHTML='<summary>百炼语音 API 凭证（独立于提示词优化器）</summary>';labels.workspace.after(credentialPanel);
    const credentialStatus=document.createElement('p');credentialPanel.append(credentialStatus);
    const keyInput=document.createElement('input');keyInput.type='password';keyInput.autocomplete='new-password';keyInput.placeholder='输入语音服务 API Key';credentialPanel.append(keyInput);
    const credentialRow=document.createElement('div');credentialRow.className='hutx-speech-row';credentialPanel.append(credentialRow);
    const credentialFeedback=document.createElement('p');credentialFeedback.setAttribute('role','status');credentialPanel.append(credentialFeedback);
    const credentialButtons=[];
    for(const [label,storage] of [['仅本次会话','session'],['安全保存到本机','persisted'],['删除本机凭证','delete']]){
        const b=document.createElement('button');b.textContent=label;credentialRow.append(b);credentialButtons.push(b);
        b.onclick=async()=>{
            if(storage!=='delete'&&!keyInput.value.trim()){credentialFeedback.textContent='✕ 请先输入 API Key';credentialFeedback.style.color='#ff8b8b';return;}
            let body=storage==='delete'?undefined:JSON.stringify({key:keyInput.value,storage});
            keyInput.value='';credentialButtons.forEach(b=>b.disabled=true);
            try{const response=await api.fetchApi(SPEECH_ROUTE+'/credential',{method:storage==='delete'?'DELETE':'POST',headers:{'Content-Type':'application/json'},body});
                body=undefined;if(!response.ok)throw Error();const status=await response.json();renderCredential(status);
                credentialFeedback.textContent=storage==='delete'?'✓ 已删除本机凭证（环境变量与会话保留）':status.active_source==='environment'?'✓ 已保存；当前环境变量优先':'✓ 已保存'+(storage==='session'?'，ComfyUI 重启后失效':'到本机安全存储');credentialFeedback.style.color=status.active_source==='environment'?'#ffc45c':'#75dea4';await refreshCatalog();
            }catch{credentialFeedback.textContent='✕ 凭证操作失败，请重新输入或检查系统安全存储支持。';credentialFeedback.style.color='#ff8b8b';}
            finally{body=undefined;credentialButtons.forEach(b=>b.disabled=false);}
        };
    }
    const row=document.createElement('div');row.className='hutx-speech-row hutx-speech-actions';root.append(row);
    const actionControls=document.createElement('div');actionControls.className='hutx-speech-action-controls';actionControls.append(labels.speed);row.append(actionControls);
    const button=(text,action)=>{const b=document.createElement('button');b.textContent=text;b.onclick=action;actionControls.append(b);return b;};
    const generate=button('生成测试音',()=>{setWidget('adopted_audio_file','');return controller.generate(parameters(),controls.reference_file.value);});
    const regenerate=button('重新生成',()=>{setWidget('adopted_audio_file','');setWidget('revision',(Number(widget('revision')?.value)||0)+1);controller.invalidate();return controller.generate(parameters(),controls.reference_file.value);});
    const cancel=button('取消',()=>controller.cancel());
    const adopt=button('采用此音频',async()=>{
        const result=controller.state.result;if(!result||controller.state.stale)return;
        adopt.disabled=true;
        try {
            const saved=await send('/adopt',{audio_id:result.audio_id});
            if(controller.state.result!==result||controller.state.stale)return;
            if(!/^hutx-speech\/adopted\/[a-f0-9]{64}\.json$/.test(saved.adopted_audio_file))throw Error();
            setWidget('adopted_audio_file',saved.adopted_audio_file);controller.adopt();node.setDirtyCanvas?.(true,true);
        }catch{status.textContent='✕ 音频采用失败，请重新生成并试听。';status.style.color='#ff8b8b';}
        finally{adopt.disabled=controller.state.adopted||controller.state.status!=='success'||controller.state.stale;}
    });
    adopt.className='hutx-speech-adopt';
    const sample=button('音色示例（仅 Mock）',()=>{
        const Context=globalThis.AudioContext||globalThis.webkitAudioContext;if(!Context)return;
        const context=new Context(),osc=context.createOscillator(),gain=context.createGain();
        osc.frequency.value=(controls.engine.value==='local'?440:550)+(controls.voice.value.endsWith('demo-b')?110:0);
        gain.gain.value=.025;osc.connect(gain);gain.connect(context.destination);osc.start();osc.stop(context.currentTime+.25);osc.onended=()=>context.close();
    });
    sample.className='hutx-speech-sample';
    const status=document.createElement('div');status.className='hutx-speech-status';status.setAttribute('role','status');root.append(status);
    const timing=document.createElement('span');timing.className='hutx-speech-timing';timing.hidden=true;row.append(timing);
    const adoptionHelp=help('生成结果与采用说明');
    const resultCard=document.createElement('section');resultCard.className='hutx-speech-result';resultCard.hidden=true;root.append(resultCard);
    const resultHeader=document.createElement('div');resultHeader.className='hutx-speech-result-header';resultCard.append(resultHeader);
    const resultHeading=document.createElement('div');resultHeading.className='hutx-speech-result-heading';resultHeader.append(resultHeading);
    const resultTitle=document.createElement('strong');resultTitle.textContent='生成结果';resultHeading.append(resultTitle);
    const player=document.createElement('audio');player.className='hutx-speech-result-audio';player.controls=true;player.hidden=true;resultCard.append(player);
    const download=document.createElement('a');download.textContent='下载 WAV';download.download='hutx-speech.wav';download.hidden=true;resultHeader.append(download);
    const targets=document.createElement('details');targets.innerHTML='<summary>视频接入能力（Local AUDIO 桥接）</summary>';root.append(targets);
    const bridgeHelp=help('口播接线与时长说明','先采用口播，再将 AUDIO 接入本地视频输入的 driver_audio；确认模型家族与冲突策略。当前安全帧预算最多 14.375 秒，不自动截断。');
    targets.querySelector('summary').append(bridgeHelp);bridgeHelp.addEventListener('click',e=>e.preventDefault());
    const debug=document.createElement('details');debug.className='hutx-speech-debug';debug.hidden=true;
    const debugTitle=document.createElement('summary');debugTitle.textContent='开发调试';debug.append(debugTitle,labels.mock_demo);root.append(debug);
    let syncing=false,disposed=false,lastAudio=null,availableCatalog=null;
    const widget=name=>node.widgets?.find(w=>w.name===name);
    let referenceSource='';
    function renderReference(){
        const file=controls.reference_file.value;referenceCard.hidden=controls.mode.value!=='clone';if(referenceCard.hidden)referencePlayer.pause();
        referenceName.hidden=referencePlayer.hidden=removeReference.hidden=!file;
        chooseReference.textContent=file?'↻':'上传参考音频';chooseReference.dataset.icon=String(!!file);
        chooseReference.title=file?'更换参考音频':'上传参考音频';chooseReference.setAttribute('aria-label',chooseReference.title);
        referenceName.value=node.properties?.hutx_speech_reference_name||file.replaceAll('\\','/').split('/').pop()||'';
        if(referenceSource!==file){referencePlayer.pause();referenceSource=file;
            if(file){const parts=file.replaceAll('\\','/').split('/');const filename=parts.pop();referencePlayer.src=api.apiURL('/view?'+new URLSearchParams({filename,subfolder:parts.join('/'),type:'input'}));}
            else referencePlayer.removeAttribute('src');
        }
    }
    function setWidget(name,value){if(widget(name))widget(name).value=value;}
    function parameters(){return {engine:controls.engine.value,mode:controls.mode.value,text:controls.text.value,
        reference_text:controls.reference_text.value,voice:controls.voice.value,speed:Number(speed.value),
        mock_demo:controls.mock_demo.checked,revision:Number(widget('revision')?.value)||0,
        cloud_model:controls.cloud_model.value,workspace:controls.workspace.value};}
    function renderFields(){
        debugTitle.textContent=controls.mock_demo.checked?'开发调试 · Mock 测试音已启用':'开发调试';
        if(controls.mock_demo.checked)debug.open=true;
        const clone=controls.mode.value==='clone';labels.reference_file.hidden=true;upload.hidden=true;renderReference();
        cloudUploadInfo.hidden=!clone||controls.engine.value!=='cloud'||controls.mock_demo.checked;
        cloudUploadInfo.textContent=availableCatalog?.engines?.find(e=>e.id==='cloud')?.clone_upload_configured
            ?'克隆上传：已配置自有 OSS。临时链接 10 分钟有效，注册结束后删除录音。'
            :'克隆上传：尚未配置自有 OSS。需在本机设置 OSS 环境变量；系统预设音色无需 OSS。';
        labels.reference_text.hidden=true;labels.voice.hidden=clone;sample.hidden=clone||!controls.mock_demo.checked;
        labels.cloud_model.hidden=labels.workspace.hidden=credentialPanel.hidden=controls.engine.value!=='cloud';
        for(const option of controls.cloud_model.options)option.disabled=option.value!=='auto' &&
            (clone?['cosyvoice-v3-flash','qwen-audio-3.1-tts-flash'].includes(option.value):!['cosyvoice-v3-flash','qwen-audio-3.1-tts-flash'].includes(option.value));
        if(controls.cloud_model.selectedOptions[0]?.disabled)controls.cloud_model.value='auto';
        voiceName.hidden=saveVoice.hidden=true;
    }
    function voices(selected){controls.voice.replaceChildren();
        const items=controls.mock_demo.checked?['a','b'].map(s=>({id:controls.engine.value+':demo-'+s,name:'Mock 测试音 '+s.toUpperCase()})):
            availableCatalog?.engines?.find(e=>e.id===controls.engine.value)?.voices||[];
        const builtinNames={'local:official-a':'温柔女声','local:official-b':'沉稳男声'};
        const groups=new Map();
        for(const item of items){const o=document.createElement('option');o.value=item.id;o.textContent=builtinNames[item.id]||item.name;
            if(item.group){let group=groups.get(item.group);if(!group){group=document.createElement('optgroup');group.label=item.group;groups.set(item.group,group);controls.voice.append(group);}group.append(o);}else controls.voice.append(o);}
        if(!items.length){const o=document.createElement('option');o.value='';o.textContent=controls.engine.value==='local'?'请先以参考录音保存本机音色':'正在读取音色列表';controls.voice.append(o);}
        if([...controls.voice.options].some(o=>o.value===selected))controls.voice.value=selected;
    }
    function persist(){syncing=true;for(const [name,value] of Object.entries({...parameters(),reference_file:controls.reference_file.value}))setWidget(name,value);syncing=false;node.setDirtyCanvas?.(true,true);}
    const send=async(path,data)=>{
        const response=await api.fetchApi(SPEECH_ROUTE+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        if(!response.ok){const body=await response.json().catch(()=>({}));const error=Error('Speech request failed');error.code=body.code;throw error;}return response.json();
    };
    const controller=createSpeechController({send,changed:state=>{
        const busy=state.status==='running',mock=controls.mock_demo.checked;
        const ready=mock||availableCatalog?.engines?.find(e=>e.id===controls.engine.value)?.available;
        generate.disabled=regenerate.disabled=busy||!ready;
        generate.textContent=mock?'生成测试音':'生成口播';
        const adopted=state.adopted||/^hutx-speech\/adopted\/[a-f0-9]{64}\.json$/.test(widget('adopted_audio_file')?.value||'');
        adopt.dataset.adopted=String(adopted);adopt.textContent=adopted?'✓ 已采用':'采用此音频';
        adopt.setAttribute('aria-pressed',String(adopted));
        adopt.dataset.ready=String(!adopted&&state.status==='success'&&!state.stale&&!!state.result);
        cancel.hidden=!busy;adopt.disabled=adopted||state.status!=='success'||state.stale||!state.result;
        const label={running:'● 生成中',success:state.result?.report?.is_mock?'✓ Mock 完成':'✓ 生成完成',error:'✕ 失败',cancelled:'■ 已取消',idle:''}[state.status];
        const showAdoptionHelp=state.status==='success'||(adopted&&state.status==='idle');
        timing.hidden=!label;timing.dataset.state=state.status;timing.textContent=label?`${label} ${state.elapsed.toFixed(busy?1:2)}s`:'';
        status.textContent=showAdoptionHelp||state.status==='cancelled'?'':state.message;
        if(showAdoptionHelp){adoptionHelp.helpText=state.message;(state.result?resultHeading:status).append(adoptionHelp);}
        status.style.color={running:'#ffc45c',success:'#75dea4',error:'#ff8b8b',cancelled:'#b1c2cd',idle:'#b1c2cd'}[state.status];
        timing.style.color=status.style.color;
        const id=state.result?.audio_id||null;
        resultCard.hidden=!id;resultTitle.textContent=state.adopted?'生成结果 · 已采用':'生成结果';
        if(lastAudio!==id){player.pause();lastAudio=id;player.hidden=download.hidden=!id;if(id){const url=api.apiURL(SPEECH_ROUTE+'/audio/'+id);player.src=url;download.href=url;}else{player.removeAttribute('src');download.removeAttribute('href');}}
        onState(state);
    }});
    for(const [name,el] of Object.entries(controls))el.addEventListener('input',()=>{
        if(syncing)return;setWidget('adopted_audio_file','');if(name==='engine'||name==='mock_demo')voices();renderFields();persist();controller.invalidate();
    });
    upload.addEventListener('change',async()=>{
        const file=upload.files?.[0];if(!file)return;setWidget('adopted_audio_file','');controller.invalidate();upload.disabled=true;
        try{const form=new FormData();form.append('image',file);form.append('type','input');form.append('subfolder','hutx-speech');
            const response=await api.fetchApi('/upload/image',{method:'POST',body:form});if(!response.ok)throw Error();
            const data=await response.json();if(disposed)return;
            controls.reference_file.value=[data.subfolder,data.name].filter(Boolean).join('/');controls.reference_text.value='';
            node.properties||={};node.properties.hutx_speech_reference_name=file.name;persist();controller.invalidate();renderReference();
        }catch{if(!disposed){status.textContent='✕ 上传失败，请选择 PCM16 WAV。';status.style.color='#ff8b8b';}}
        finally{upload.disabled=false;upload.value='';}
    });
    function hydrate(){syncing=true;controller.invalidate();for(const [name,el] of Object.entries(controls)){if(name==='voice')continue;const value=widget(name)?.value;if(el.type==='checkbox')el.checked=!!value;else if(value!==undefined)el.value=value;}voices(widget('voice')?.value);renderFields();syncing=false;controller.invalidate();if(widget('adopted_audio_file')?.value)controller.snapshotRestored();}
    for(const name of SPEECH_FIELDS){
        const w=widget(name);if(!w)continue;
        w.hidden=true;w.options||={};w.options.hidden=true;w.computeSize=()=>[0,-4];
        for(const element of [w.element,w.inputEl])if(element){element.hidden=true;element.style.display='none';}
    }
    const canvasHost=embedded?null:createCanvasPanelHost(root);
    const dom=embedded?null:node.addDOMWidget('speech_panel','div',canvasHost,{serialize:false,getValue:()=>null});
    const responsive=dom?bindResponsiveDomHost(node,dom,canvasHost,()=>{},root):{destroy(){}};
    const configured=node.onConfigure;node.onConfigure=function(){configured?.apply(this,arguments);hydrate();};
    const executed=node.onExecuted;node.onExecuted=function(message){executed?.apply(this,arguments);if(message?.speech_result?.[0])controller.executed(message.speech_result[0]);};
    const removed=node.onRemoved;node.onRemoved=function(){disposed=true;tooltip.remove();controller.destroy();responsive.destroy();player.pause();referencePlayer.pause();referencePlayer.removeAttribute('src');removed?.apply(this,arguments);};
    hydrate();if(!embedded)node.setSize?.([Math.max(380,node.size?.[0]||460),850]);
    function renderCredential(data){credentialStatus.textContent=`当前生效：${{environment:'环境变量',session:'本次会话',persisted:'本机安全存储',none:'未配置'}[data.active_source]||'未配置'}\n会话：${data.session_configured?'已配置':'未配置'} / 本机：${data.persisted_configured?'已保存':'未保存'}`;}
    async function refreshCatalog(){try{
        const response=await api.fetchApi(SPEECH_ROUTE+'/catalog');if(!response.ok)throw Error();const data=await response.json();if(disposed)return;
        availableCatalog=data;notice.helpText=data.notice||'Mock 只生成测试音。';
        const old=controls.voice.value;voices(old);persist();renderFields();
        // Refresh availability without discarding a valid audio preview.
        generate.disabled=regenerate.disabled=controller.busy||!(controls.mock_demo.checked||data.engines?.find(e=>e.id===controls.engine.value)?.available);
        for(const el of [...targets.querySelectorAll('.hutx-speech-target')])el.remove();
        const seen=new Set();
        for(const target of data.video_targets||[]){
            const identity=JSON.stringify([target.backend,target.mode,target.model_family,target.reason]);if(seen.has(identity))continue;seen.add(identity);
            const line=document.createElement('div');line.className='hutx-speech-target';
            const name=document.createElement('span'),description=document.createElement('span');
            name.textContent=`${target.backend.toUpperCase()} · ${target.mode.toUpperCase()}`;description.textContent=target.reason;
            if(target.model_family){const model=document.createElement('small');model.textContent=target.model_family;name.append(model);}
            line.append(name,description);targets.append(line);
        }
        if(data.credential)renderCredential(data.credential);
    }catch{if(!disposed)notice.helpText='无法读取运行状态，请检查 ComfyUI 日志；不会自动调用服务。';}}
    saveVoice.onclick=async()=>{saveVoice.disabled=true;try{const response=await api.fetchApi(SPEECH_ROUTE+'/voices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:voiceName.value,reference_file:controls.reference_file.value,reference_text:controls.reference_text.value})});if(!response.ok)throw Error();await refreshCatalog();status.textContent='✓ 本机音色已保存，可切换到预设音色使用。';}catch{status.textContent='✕ 请检查音色名称、参考 WAV 与原文。';}finally{saveVoice.disabled=false;}};
    refreshCatalog();
    return {root,canvasHost,controller,controls,generate,regenerate,cancel,adopt,player,parameters,hydrate,
        labels,heading,credentialPanel,cloudUploadInfo,targets,debug,refreshCatalog};
}

app.registerExtension({name:'HuTX.Speech.MockPreview',beforeRegisterNodeDef(nodeType,nodeData){
    if(nodeData.name!=='GHSpeechInputGH')return;
    const created=nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated=function(){const result=created?.apply(this,arguments);this.hutxWorkbenchPanel=createSpeechPanel(this);return result;};
}});
