import {app} from '/scripts/app.js';
import {createSpeechPanel} from './speech_input.js';
import {bindResponsiveDomHost,createCanvasPanelHost} from './responsive_dom_host.js';
import {multiSpeechTheme} from './multi_speech_theme.js';
import {enhanceSpeechAudio} from './speech_audio_player.js';

const ROLE_DEFAULTS={engine:'local',mode:'clone',text:'',reference_text:'',reference_file:'',voice:'',speed:1,mock_demo:false,revision:0,cloud_model:'auto',workspace:'',adopted_audio_file:''};
const SHARED=['engine','cloud_model','workspace','mock_demo'];
export function readMultiRole(raw,letter){
    let parsed={};try{parsed=JSON.parse(raw||'{}');}catch{}
    const clean={...ROLE_DEFAULTS,name:`角色 ${letter}`,enabled:true,collapsed:false,reference_name:''};
    for(const key of Object.keys(clean))if(parsed&&Object.hasOwn(parsed,key)&&typeof parsed[key]===typeof clean[key])clean[key]=parsed[key];
    return clean;
}

export function createMultiSpeechPanel(node){
    const root=document.createElement('div');root.className='hutx-multi-speech hutx-speech-root';
    const style=document.createElement('style');style.textContent=`
      .hutx-multi-speech{container-type:inline-size;overflow:auto}
      .hutx-multi-cards{display:grid;grid-template-columns:minmax(0,1fr);gap:12px}
      .hutx-multi-speech .hutx-role{margin:0;padding:8px;border:1px solid #426b7b;border-radius:9px;align-self:start}
      .hutx-role>summary{display:flex;align-items:center;gap:8px;list-style:none}
      .hutx-role .hutx-role-toggle{border:0;background:transparent;padding:0;width:16px;color:#8bdce7;flex:0 0 auto}
      .hutx-role-toggle::before{content:'▸'}.hutx-role[open] .hutx-role-toggle::before{content:'▾'}
      .hutx-role>summary input[type=text]{flex:1;width:0;margin:0;background:transparent;border-color:transparent;font-weight:600}
      .hutx-role-state{font-size:12px;white-space:nowrap;color:#9acbd5}
      .hutx-role>.hutx-speech-root{padding:2px;overflow:visible}
      .hutx-role:not([data-role=A]) label:has([data-field=engine]),
      .hutx-role:not([data-role=A]) label:has([data-field=cloud_model]),
      .hutx-role:not([data-role=A]) label:has([data-field=workspace]),
      .hutx-role:not([data-role=A]) label:has([data-field=mock_demo]){display:none!important}
      .hutx-role .hutx-speech-actions{grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:8px}
      .hutx-role .hutx-speech-timing{min-height:30px;justify-self:end}
      .hutx-role[data-enabled=false]>.hutx-speech-root{display:none}
      .hutx-multi-batch{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
      @container (min-width:1080px){.hutx-multi-cards{grid-template-columns:repeat(3,minmax(0,1fr))}}
    `+multiSpeechTheme;root.append(style);
    const note=document.createElement('p');note.className='hutx-multi-instructions';
    const guide=document.createElement('button');guide.type='button';guide.textContent='接线与使用说明 ⓘ';guide.title='A / B / C → Local reference_audio_1 / 2 / 3。空台词或停用角色不输出音频；三路为独立参考，不自动拼接或编排对白。';guide.setAttribute('aria-label',guide.title);note.append(guide);root.append(note);
    const shared=document.createElement('div');shared.className='hutx-multi-shared';root.append(shared);
    const batch=document.createElement('div');batch.className='hutx-multi-batch';root.append(batch);
    const cards=document.createElement('div');cards.className='hutx-multi-cards';root.append(cards);
    const roles=[];let restoring=true,disposed=false,batching=false,stop=false,lease=false,adopting=false;
    const widget=letter=>node.widgets?.find(w=>w.name===`role_${letter}`);
    function persist(){if(restoring||disposed)return;for(const r of roles){const value={...r.config,...Object.fromEntries(r.adapter.widgets.map(w=>[w.name,w.value])),collapsed:!r.card.open,reference_name:r.adapter.properties.hutx_speech_reference_name||''};widget(r.letter).value=JSON.stringify(value);}node.setDirtyCanvas?.(true,true);}
    const button=(label,action)=>{const b=document.createElement('button');b.textContent=label;b.onclick=action;batch.append(b);return b;};
    const batchGenerate=button('生成待更新角色',async()=>{
        if(batching||lease||roles.some(r=>r.panel.controller.busy))return;
        batching=true;stop=false;update();
        try{for(const r of roles){
            if(stop||disposed)break;
            if(!r.config.enabled||!r.panel.controls.text.value.trim()||r.adapter.widgets.find(w=>w.name==='adopted_audio_file').value||(!r.panel.controller.state.stale&&r.panel.controller.state.result))continue;
            await run(r,false,true);
            if(r.panel.controller.state.status!=='success')break;
        }}finally{batching=false;persist();update();}
    });
    const batchCancel=button('停止批量生成',()=>{stop=true;roles.forEach(r=>r.panel.controller.cancel());});
    const batchAdopt=button('采用全部已生成结果',async()=>{
        if(batching||lease||adopting)return;adopting=true;update();
        try{for(const r of roles)if(r.config.enabled&&!r.panel.adopt.disabled)await r.panel.adopt.onclick();}
        finally{adopting=false;persist();update();}
    });
    batchGenerate.classList.add('hutx-primary');
    function update(){
        if(disposed)return;
        batchGenerate.disabled=batching||lease||adopting;batchCancel.hidden=!batching;
        batchAdopt.disabled=batching||lease||adopting||!roles.some(r=>r.config.enabled&&!r.panel.adopt.disabled);
        for(const r of roles){
            const s=r.panel.controller.state,saved=r.adapter.widgets.find(w=>w.name==='adopted_audio_file').value;
            r.status.textContent=!r.config.enabled?'已停用':saved?'✓ 已采用':({running:'● 生成中',success:'待采用',error:'✕ 失败',cancelled:'■ 已取消'})[s.status]||'待生成';
            r.status.dataset.state=!r.config.enabled?'disabled':saved?'adopted':s.status;
            r.panel.adopt.hidden=s.status==='running';
            // One generator for the node, including individual clicks during batch work.
            if(batching||lease||adopting||!r.config.enabled){r.panel.generate.disabled=r.panel.regenerate.disabled=true;}
            else {r.panel.generate.disabled=r.panel.regenerate.disabled=false;}
        }
    }
    async function run(r,regenerate=false,fromBatch=false){
        if(lease||(!fromBatch&&batching)||!r.config.enabled)return;
        lease=true;update();
        try{return await (regenerate?r.rawRegenerate:r.rawGenerate)();}
        finally{lease=false;persist();update();}
    }
    for(const letter of 'ABC'){
        const config=readMultiRole(widget(letter)?.value,letter);
        const card=document.createElement('details');card.className='hutx-role';card.dataset.role=letter;card.open=!config.collapsed;cards.append(card);
        const summary=document.createElement('summary');card.append(summary);
        const toggle=document.createElement('button');toggle.className='hutx-role-toggle';toggle.setAttribute('aria-label',`展开或折叠角色 ${letter}`);toggle.onclick=e=>{e.preventDefault();card.open=!card.open;config.collapsed=!card.open;persist();};summary.append(toggle);
        const enabled=document.createElement('input');enabled.type='checkbox';enabled.checked=config.enabled;enabled.setAttribute('aria-label',`启用角色 ${letter}`);summary.append(enabled);
        const letterTag=document.createElement('span');letterTag.className='hutx-role-letter';letterTag.textContent=letter;summary.append(letterTag);
        const name=document.createElement('input');name.type='text';name.maxLength=80;name.value=config.name;name.setAttribute('aria-label',`角色 ${letter} 名称`);summary.append(name);
        const status=document.createElement('span');status.className='hutx-role-state';summary.append(status);
        for(const input of [enabled,name])input.addEventListener('click',e=>e.stopPropagation());
        const adapter={widgets:Object.keys(ROLE_DEFAULTS).map(key=>({name:key,value:config[key]})),properties:{hutx_speech_reference_name:config.reference_name},setDirtyCanvas:()=>persist()};
        const panel=createSpeechPanel(adapter,{embedded:true,onState:()=>{persist();queueMicrotask(update);}});
        const r={letter,config,card,adapter,panel,status,name,enabled,rawGenerate:panel.generate.onclick,rawRegenerate:panel.regenerate.onclick};roles.push(r);
        card.append(panel.root);panel.heading.hidden=true;panel.targets.hidden=true;
        const actionControls=panel.root.querySelector('.hutx-speech-action-controls');
        const timing=panel.root.querySelector('.hutx-speech-timing');
        if(actionControls&&timing)actionControls.append(timing);
        panel.generate.classList.add('hutx-primary');
        panel.labels.text.firstChild.textContent='新台词';panel.controls.text.placeholder='输入这个角色要说的话…';
        panel.labels.mode.firstChild.textContent='声音来源';panel.labels.voice.firstChild.textContent='预设音色';
        const audioSkin=enhanceSpeechAudio(panel.root),disposePanel=adapter.onRemoved;
        adapter.onRemoved=()=>{audioSkin.destroy();disposePanel?.();};
        for(const field of SHARED){const wrap=panel.labels[field];if(letter==='A')shared.append(wrap);else wrap.hidden=true;}
        if(letter==='A'){
            panel.labels.workspace.after(panel.credentialPanel);shared.append(panel.cloudUploadInfo);
            shared.append(panel.debug);panel.debug.append(panel.labels.mock_demo);
        }else {panel.credentialPanel.remove();panel.cloudUploadInfo.remove();panel.debug.remove();}
        panel.generate.onclick=()=>run(r);panel.regenerate.onclick=()=>run(r,true);
        card.dataset.enabled=String(config.enabled);
        enabled.onchange=()=>{config.enabled=enabled.checked;card.dataset.enabled=String(config.enabled);if(!config.enabled)panel.controller.cancel();persist();update();};
        name.oninput=()=>{config.name=name.value;persist();};
        card.addEventListener('toggle',()=>{config.collapsed=!card.open;persist();});
        const native=widget(letter);if(native){native.serializeValue=()=>{persist();return native.value;};native.hidden=true;native.options||={};native.options.hidden=true;native.computeSize=()=>[0,-4];for(const e of [native.element,native.inputEl])if(e){e.hidden=true;e.style.display='none';}}
    }
    for(const key of SHARED)roles[0].panel.controls[key].addEventListener('input',()=>{
        for(const r of roles.slice(1)){
            const source=roles[0].panel.controls[key],target=r.panel.controls[key];target.value=source.value;target.checked=source.checked;
            target.dispatchEvent(new Event('input',{bubbles:true}));
        }persist();update();
    });
    const canvasHost=createCanvasPanelHost(root);
    const dom=node.addDOMWidget('multi_speech_panel','div',canvasHost,{serialize:false});
    const responsive=bindResponsiveDomHost(node,dom,canvasHost,()=>{},root);
    const configure=node.onConfigure;node.onConfigure=function(){configure?.apply(this,arguments);restoring=true;
        for(const r of roles){Object.assign(r.config,readMultiRole(widget(r.letter)?.value,r.letter));for(const w of r.adapter.widgets)w.value=r.config[w.name];r.adapter.properties.hutx_speech_reference_name=r.config.reference_name;r.panel.hydrate();r.name.value=r.config.name;r.enabled.checked=r.config.enabled;r.card.dataset.enabled=String(r.config.enabled);r.card.open=!r.config.collapsed;}
        restoring=false;persist();update();
    };
    const serialize=node.onSerialize;node.onSerialize=function(){persist();return serialize?.apply(this,arguments);};
    const removed=node.onRemoved;node.onRemoved=function(){disposed=true;stop=true;roles.forEach(r=>r.adapter.onRemoved?.());responsive.destroy();removed?.apply(this,arguments);};
    restoring=false;persist();update();node.setSize?.([Math.max(460,node.size?.[0]||460),950]);
    return {root,canvasHost,roles,batchGenerate,batchAdopt,batchCancel};
}

app.registerExtension({name:'HuTX.Speech.MultiCharacter',beforeRegisterNodeDef(nodeType,nodeData){
    if(nodeData.name!=='GHMultiSpeechInputGH')return;
    const created=nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated=function(){const result=created?.apply(this,arguments);this.hutxWorkbenchPanel=createMultiSpeechPanel(this);return result;};
}});
