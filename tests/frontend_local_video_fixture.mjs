// Actual Local controller and shared components; all I/O mocked.
import fs from 'node:fs';
import vm from 'node:vm';
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const read=name=>fs.readFileSync(new URL('../web/js/'+name,import.meta.url),'utf8');
const strip=s=>s.replace(/^import[\s\S]*?from\s+["'][^"']+["'];\s*/gm,'').replace(/\bexport /g,'');
class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.value = ''; this.listeners = {}; this.attributes = {}; this.selectionStart = 0; this.selectionEnd = 0;
        this.dataset={}; this.classList = {add(){},remove(){},toggle(){}}; }
    append(...items) { this.children.push(...items); for (const item of items) if (item && typeof item === 'object') item.parent = this; }
    after(item) {const index=this.parent.children.indexOf(this);this.parent.children.splice(index+1,0,item);item.parent=this.parent;}
    appendChild(item) { this.append(item); return item; }
    replaceChildren(...items) { this.children = items; }
    setAttribute(key, value) { this.attributes[key] = value; }
    querySelector(selector) { return this.children.find(el => el.attributes?.['aria-selected'] === 'true') || null; }
    scrollIntoView() {}
    getBoundingClientRect() { return {left:100, right:520, top:100, bottom:220, width:420, height:120}; }
    getClientRects() { return [this.getBoundingClientRect()]; }
    getContext(){return {drawImage(){}};}
    toDataURL(){return 'data:image/jpeg;base64,MOCK_IMAGE';}
    get clientWidth() { return 418; }
    get offsetWidth() { return 420; }
    get offsetHeight() { return 120; }
    get scrollTop() { return 0; }
    get scrollLeft() { return 0; }
    get scrollHeight() { return 100; }
    closest() { return null; }
    focus() { context.document.activeElement = this; }
    setRangeText(text, start, end) { this.value = this.value.slice(0,start) + text + this.value.slice(end); this.selectionStart = this.selectionEnd = start + text.length; }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(item => item !== this); }
    addEventListener(event, handler) { (this.listeners[event] ||= []).push(handler); }
    removeEventListener(event, handler) { this.listeners[event] = (this.listeners[event] || []).filter(item => item !== handler); }
    emit(event, extras = {}) {
        const e = {key:'', preventDefault(){this.prevented=true;}, stopPropagation(){}, ...extras};
        this['on' + event]?.(e);
        for (const handler of this.listeners[event] || []) handler(e);
        return e;
    }
}
const body=new Element('body'),requests=[],alerts=[],visualReads=[];
const context=vm.createContext({Blob,FormData,URLSearchParams,AbortController,performance,setInterval,clearInterval,setTimeout,clearTimeout,
    addEventListener(){},removeEventListener(){},innerWidth:1024,innerHeight:768,
    getComputedStyle:()=>({borderLeftWidth:'1px',borderRightWidth:'1px',fontSize:'12px',lineHeight:'18px'}),
    document:{body,head:new Element('head'),getElementById(id){const find=node=>node.id===id?node:(node.children||[]).filter(child=>typeof child==='object').map(find).find(Boolean);return find(this.head)||find(this.body)||null;},createElement:tag=>new Element(tag),createTextNode:text=>text},
    Option:class extends Element{constructor(text,value){super('option');this.textContent=text;this.value=value;}},
    Image:class {constructor(){this.naturalWidth=1920;this.naturalHeight=1080;}set src(url){visualReads.push(url);queueMicrotask(()=>this.onload());}},
    navigator:{language:'zh'},alert:message=>alerts.push(message),INPUT:input,
    api:{fetchApi:async(url,options={})=>{
        const requestBody=options.body instanceof FormData?null:options.body?JSON.parse(await options.body.text()):null;
        requests.push({url,body:requestBody});let data={},ok=true;
        if(url==='/upload/image')data={name:input.filename||'中文 file.png',subfolder:'local'};
        else if(url.includes('/local-media-info?'))data={width:1920,height:1080,has_audio:input.videoAudio!==false};
        else if(url.endsWith('/config'))data={provider:'dashscope',mode:'api',read_media:false,...input.config};
        else if(url.includes('/credential?'))data={provider:new URLSearchParams(url.split('?')[1]).get('provider'),configured:true,active_source:'persisted',persisted_configured:true};
        else if(url.endsWith('/secret'))data={credential_ref:'ghopt_test_xxx'};
        else if(url.endsWith('/optimize')){
            if(context.optimizeHook)await context.optimizeHook();
            data=input.optimizeError?{error:input.optimizeError}:{prompt:input.optimizedPrompt||'Optimized scene.',report:'{"status":"optimized"}'};ok=!input.optimizeError;
        }
        else if(!url.endsWith('/cancel'))throw new Error('Unexpected API operation '+url);
        return {ok,status:ok?200:400,json:async()=>data,text:async()=>JSON.stringify(data)};
    }},
});
vm.runInContext(`const app={graph:{},registerExtension(){},queuePrompt:async()=>{globalThis.queued++;}};globalThis.queued=0;globalThis.app=app;\n`+
    ['prompt_optimizer_shared.js','responsive_dom_host.js','gh_video_input_shared.js','video_input_components.js','local_video_input_state.js','local_driver_preview.js','gh_local_video_input.js'].map(name=>strip(read(name))).join('\n')+`
globalThis.makeNode=(saved,values={})=>{
 const defaults={model_name:'MODEL_FILE.safetensors',clip_name:'CLIP_FILE.safetensors',video_vae_name:'VIDEO_VAE.safetensors',audio_vae_name:'AUDIO_VAE.safetensors',aspect:'16:9',megapixels:0.5,duration_seconds:5,main_mode:'text_keyframes',prompt:'Initial Local prompt',gh_local_state_json:''};
 const node={graph:app.graph,mode:0,properties:saved?{gh_local_video_state:JSON.stringify(saved)}:{},widgets:[
  ...Object.entries({...defaults,...values}).map(([name,value])=>({name,value,options:{values:[String(value),'alternate.safetensors']}})),...LOCAL_SLOTS.map(name=>({name,value:''}))],
  addDOMWidget(name,type,root){this.root=root;},setDirtyCanvas(){}};
 if(INPUT.reactiveWidgets)for(const w of node.widgets){let value=w.value;Object.defineProperty(w,'value',{get:()=>value,set:next=>{value=next;w.callback?.(next);}});}
 node.controller=createLocalVideoPanel(node);return node;
};globalThis.node=makeNode(INPUT.state,INPUT.values);
globalThis.entries=()=>{const state=node.controller.serialize();return localPickerEntries(state.mode,new Map(state.media),new Map(state.media.map(([,e])=>[e.name,{has_audio:INPUT.videoAudio!==false}])));};
`,context);
const all=el=>[el,...(el.children||[]).flatMap(e=>typeof e==='object'?all(e):[])];
const find=cls=>all(context.node.root).find(e=>e.className===cls);
const snapshots=[],results=[];
context.optimizeHook=async()=>{
    if(input.duringOptimize==='edit'){context.node.controller.prompt.value='Edited while waiting';context.node.controller.prompt.emit('input');}
    if(input.duringOptimize==='cancel')await context.node.controller.optimizer.cancel();
    if(input.duringOptimize==='duplicate')await context.node.controller.optimizer.run();
};
await context.node.controller.ready();
for(const action of input.actions||[]) {
    if(action.type==='reload'){
        const state=context.node.controller.serialize(),values=Object.fromEntries(context.node.widgets.map(w=>[w.name,w.value]));
        context.node.onRemoved();context.node=context.makeNode(state,values);await context.node.controller.ready();
    }
    if(action.type==='configure')context.node.onConfigure({properties:{gh_local_video_state:JSON.stringify(action.state)}});
    if(action.type==='prompt'||action.type==='mode') {
        const w=context.node.widgets.find(w=>w.name===(action.type==='mode'?'main_mode':'prompt'));w.value=action.value;w.callback();
    }
    if(action.type==='upload')await context.node.controller.chooseFile(action.slot,new File(['fixture'],'fixture.png',{type:'image/png'}));
    if(action.type==='remove')all(context.node.root).find(e=>e.dataset?.slot===action.slot).children.find(e=>e.className==='gh-cloud-remove').onclick();
    if(action.type==='optimize')results.push(await context.node.controller.optimizer.run());
    if(action.type==='saveCredential') {
        await find('gh-opt-configure').onclick();
        const elements=all(body),key=elements.find(e=>e.type==='password');key.value='TEST_SECRET_123';
        await elements.find(e=>e.tag==='button'&&e.textContent==='保存').onclick();
        if(key.value!=='')throw new Error('Password field was not cleared');
    }
    if(action.type==='auto')try{await context.app.queuePrompt();results.push(true);}catch(e){results.push(e.message);}
    if(action.type==='restore')find('gh-prompt-restore').onclick();
    if(action.type==='apply')find('gh-prompt-apply').onclick();
    if(action.type==='collapse')find('gh-local-summary').onclick();
    if(action.type==='config') {const control=context.node.controller.controls.get(action.name);control.value=action.value;control.onchange?.();}
    if(action.type==='type') {const p=context.node.controller.prompt;p.focus();p.selectionStart=p.selectionEnd=action.caret??p.value.length;p.setRangeText(action.value,p.selectionStart,p.selectionEnd);p.emit('input');}
    if(action.type==='key')context.node.controller.prompt.emit('keydown',{key:action.key});
    await context.node.controller.ready();context.node.onSerialize();
    snapshots.push({state:context.node.controller.serialize(),rows:all(context.node.root).filter(e=>e.dataset?.slot).map(e=>e.dataset.slot),
        properties:JSON.parse(JSON.stringify(context.node.properties)),widgets:context.node.widgets.map(w=>[w.name,w.value]),entries:context.entries(),
        caret:context.node.controller.prompt.selectionStart,collapsed:find('gh-local-config').hidden,
        timer:find('gh-opt-timing')?.attributes['data-state'],picker:all(body).find(e=>e.className==='gh-cloud-picker')?.hidden,
        menu:all(body).find(e=>e.className==='gh-cloud-picker')?.children.map(e=>({text:e.children?.[0]?.textContent,selected:e.attributes?.['aria-selected']}))});
}
const result={snapshots,requests,state:context.node.controller.serialize(),results,queued:context.queued,alerts,visualReads};
context.node.onRemoved();process.stdout.write(JSON.stringify(result));
