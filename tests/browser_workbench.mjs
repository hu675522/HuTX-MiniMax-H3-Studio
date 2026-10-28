// Integration test of the actual frontend modules. All providers, queue and media are mocked.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {auditWorkbenchLayout} from './workbench_layout.mjs';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.HUTX_PLAYWRIGHT_MODULE || 'playwright');
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(project, '.test-artifacts/workbench'); fs.mkdirSync(out, {recursive: true});
const mocks = `
export const extensions=[]; export const events=new EventTarget(); export const calls=[];const jobHistory={};globalThis.batchPayloads=[];
let nextId=0, nextLink=0;const deletedVideos=new Set();
function makeGraph(){return {_nodes:[],links:{},extra:{},getNodeById(id){return this._nodes.find(n=>String(n.id)===String(id));},add(n){n.id=++nextId;n.graph=this;this._nodes.push(n);},remove(n){n.onRemoved?.();this._nodes.splice(this._nodes.indexOf(n),1);},change(){},setDirtyCanvas(){}};}
export const app={graph:makeGraph(),registerExtension(e){extensions.push(e);},extensionManager:{setting:{get:()=> 'zh'},registerSidebarTab(tab){globalThis.sidebar=tab;}},canvas:{selectNode(){},centerOnNode(){},setDirty(){}},async queuePrompt(){globalThis.queued++;},async graphToPrompt(){
 const output={};for(const node of this.graph._nodes){const inputs=Object.fromEntries(node.widgets.filter(w=>w.options?.serialize!==false).map(w=>[w.name,w.value]));for(const input of node.inputs){const link=this.graph.links[input.link];if(link)inputs[input.name]=[String(link.origin_id),link.origin_slot];}output[String(node.id)]={class_type:node.type,inputs};}
 return {output,workflow:{nodes:this.graph._nodes.map(n=>({id:n.id,type:n.type,properties:n.properties,widgets_values:n.widgets.map(w=>w.value)})),extra:this.graph.extra}};
}};
globalThis.app=app;globalThis.makeGraph=makeGraph;globalThis.queued=0;globalThis.queueSnapshot={queue_running:[],queue_pending:[]};globalThis.queueHistory={};
export const api={apiURL:p=>p,addEventListener:(...a)=>events.addEventListener(...a),removeEventListener:(...a)=>events.removeEventListener(...a),async queuePrompt(_,payload){
 globalThis.batchPayloads.push(payload);const id='batch-'+globalThis.batchPayloads.length;const save=Object.entries(payload.output).find(([,n])=>n.class_type==='SaveVideo')[0];jobHistory[id]={prompt:[0,id,payload.output],status:{completed:true,status_str:'success'},outputs:{[save]:{videos:[{filename:id+'.mp4',subfolder:'video',type:'output'}]}}};return {prompt_id:id};
},async fetchApi(url,options={}){
 calls.push(url); let data={};
 if(url.endsWith('/catalog'))data={engines:[{id:'local',available:true,voices:[{id:'local:official-a',name:'温柔女声'},{id:'local:official-b',name:'沉稳男声'}]}],video_targets:[],notice:'Mock runtime'};
 else if(url.endsWith('/generate')){await new Promise(r=>setTimeout(r,100));data={audio_id:'mock-audio',report:{is_mock:true}};}
 else if(url.endsWith('/adopt'))data={adopted_audio_file:'hutx-speech/adopted/'+ 'a'.repeat(64)+'.json'};
 else if(url.includes('/snapshot?'))data={audio_file:'voice.wav',duration_seconds:3};
 else if(url.includes('local-media-info'))data={width:960,height:544,has_audio:false};
 else if(url.endsWith('/config'))data={mode:'api',provider:'dashscope',auto_optimize:false};
 else if(url.endsWith('/workbench/videos')){
  const history={test:{outputs:{9:{videos:[{filename:'test.mp4',subfolder:'video',type:'output'}]}}},...jobHistory};
  data={videos:Object.entries(history).reverse().flatMap(([promptId,record])=>Object.entries(record.outputs).flatMap(([nodeId,out])=>out.videos.map(file=>({...file,promptId,nodeId,title:file.filename})))).filter(file=>!deletedVideos.has(file.filename))};
 }
 else if(url.endsWith('/workbench/videos/delete')){
  globalThis.deletePayload=JSON.parse(options.body);
  if(globalThis.failDelete)return new Response(JSON.stringify({error:'视频正在被占用，请停止预览后重试。'}),{status:400,headers:{'Content-Type':'application/json'}});
  deletedVideos.add(deletePayload.filename);data={deleted:deletePayload};
 }
 else if(url==='/queue')data=globalThis.queueSnapshot;
 else if(url.startsWith('/history/')&&globalThis.queueHistory[url.split('/').at(-1)])data={[url.split('/').at(-1)]:globalThis.queueHistory[url.split('/').at(-1)]};
 else if(url.startsWith('/history/')){const id=url.split('/').at(-1);data={[id]:jobHistory[id]};}
 else if(url.startsWith('/history'))data={test:{prompt:[0,'test',{2:{class_type:'GHLocalVideoInputDualEngineGH'}}],outputs:{9:{videos:[{filename:'test.mp4',subfolder:'video',type:'output'}]}}},...jobHistory};
 else if(url.endsWith('/assemble')){globalThis.assemblyPayload=JSON.parse(options.body);data={job_id:'b'.repeat(32),state:'running',completed:0,total:4,result:null,error:''};}
 else if(url.includes('/assemble/'))data={job_id:'b'.repeat(32),state:'complete',completed:4,total:4,result:{filename:'assembled.mp4',subfolder:'video/HuTX_Workbench',type:'output'},error:''};
 return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
}};
globalThis.testApi=api;globalThis.testEvents=events;globalThis.testCalls=calls;
const shapes={ComfySwitchNode:[['on_false','on_true'],['output']],GHMultiSpeechInputGH:[[],['audio_A','audio_B','audio_C']],GHLocalVideoInputDualEngineGH:[['driver_audio','reference_audio_1','reference_audio_2','reference_audio_3','continuation_latent','continuation_frames','continuation_audio'],['model','positive','av_latent','sampler','sigmas','video_vae','audio_vae','driver_audio_passthrough']],BasicGuider:[['model','conditioning'],['guider']],RandomNoise:[[],['noise']],SamplerCustomAdvanced:[['noise','guider','sampler','sigmas','latent_image'],['output','denoised_output']],MiniMaxH3AVDecodeT8GH:[['av_latent','video_vae','audio_vae'],['frames','generated_audio']],CreateVideo:[['images','audio'],['video']],SaveVideo:[['video'],['video']]};
const values={engine_mode:'fused_turbo',fused_model_name:'fused-ref2va.safetensors',hyperflow_base_model:'base-ref2va.safetensors',hyperflow_weights:'hyperflow.safetensors',hyperflow_strength:1,strict_architecture:true,clip_name:'clip.safetensors',video_vae_name:'video.safetensors',audio_vae_name:'audio.safetensors',aspect:'adaptive',megapixels:0.5,duration_seconds:5,main_mode:'text_keyframes',prompt:'',gh_local_state_json:'',driver_model_family:'unconfirmed',driver_conflict:'reject_conflicts',driver_slot:'auto',fused_steps:4,chunk_ffn_enabled:true,chunk_count:4,chunk_threshold:4096,sla_enabled:true,sla_sparsity:0.8,sla_block_size:'64',sla_min_seq_len:8192,shift_video:12,shift_audio:3};
class BaseNode{
 constructor(type){this.type=type;this.title=type;this.pos=[0,0];this.size=[600,900];this.mode=0;this.properties={};this.inputs=(shapes[type]?.[0]||[]).map(name=>({name,link:null}));this.outputs=(shapes[type]?.[1]||[]).map(name=>({name,links:[]}));
 const defaults=type==='ComfySwitchNode'?{switch:true}:type==='GHMultiSpeechInputGH'?Object.fromEntries('ABC'.split('').map(l=>['role_'+l,JSON.stringify({mode:'preset',voice:'local:official-a',text:'',enabled:true,mock_demo:true})])):type==='GHLocalVideoInputDualEngineGH'?{...values,...Object.fromEntries(['first_frame','last_frame','hybrid_audio',...Array.from({length:9},(_,i)=>'ref_image_'+(i+1)),...Array.from({length:3},(_,i)=>'ref_video_'+(i+1)),...Array.from({length:3},(_,i)=>'ref_audio_'+(i+1))].map(k=>[k,'']))}:type==='CreateVideo'?{fps:30}:type==='RandomNoise'?{noise_seed:0}:type==='SaveVideo'?{filename_prefix:'video/ComfyUI'}:{};
 this.widgets=Object.entries(defaults).map(([name,value])=>({name,value,options:{values:[String(value)],min:0.1,max:100,step:1}}));this.onNodeCreated?.();}
 addDOMWidget(name,type,root,options={}){const frame=document.createElement('div');frame.className='dom-widget';frame.append(root);document.querySelector('#canvas').append(frame);return {name,element:root,options};}
 setDirtyCanvas(){} setSize(s){this.size=s;}
 connect(index,target,slot){const id=++nextLink,link={id,origin_id:this.id,origin_slot:index,target_id:target.id,target_slot:slot};this.graph.links[id]=link;this.outputs[index].links.push(id);target.inputs[slot].link=id;return link;}
 disconnectInput(slot){delete this.graph.links[this.inputs[slot].link];this.inputs[slot].link=null;}
}
export function registerNodes(){const classes={};for(const type of Object.keys(shapes)){class Node extends BaseNode{constructor(){super(type);}}for(const e of extensions)e.beforeRegisterNodeDef?.(Node,{name:type});classes[type]=Node;}globalThis.LiteGraph={registered_node_types:classes,createNode:type=>classes[type]?new classes[type]():null};}
`;
const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    if(url.pathname==='/view'&&process.env.HUTX_TEST_VIDEO){res.setHeader('Content-Type','video/mp4');return res.end(fs.readFileSync(process.env.HUTX_TEST_VIDEO));}
    res.setHeader('Content-Type', 'text/javascript');
    if (url.pathname === '/mocks.js') return res.end(mocks);
    if (url.pathname === '/scripts/app.js' || url.pathname === '/scripts/api.js') return res.end('export * from "/mocks.js";');
    if (url.pathname.startsWith('/web/js/') && /^[a-z_]+\.js$/.test(url.pathname.split('/').at(-1))) return res.end(fs.readFileSync(path.join(project, url.pathname)));
    if (url.pathname === '/') {res.setHeader('Content-Type','text/html');return res.end('<style>body{margin:0;background:#182a39}#sidebar{width:540px;height:100vh;margin-left:auto}#canvas{position:fixed;left:-10000px;width:1200px}.dom-widget{width:100%}</style><div id="canvas"></div><div id="sidebar"></div>');}
    res.statusCode = 404; res.end('not found');
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({channel:'msedge',headless:true});
try {
    const page = await browser.newPage({viewport:{width:1440,height:1100}}), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(async () => {
        for (const name of ['speech_input','multi_speech_input','gh_local_video_input','workbench']) await import('/web/js/'+name+'.js');
        const {extensions,registerNodes}=await import('/mocks.js'); registerNodes();
        for(const extension of extensions) await extension.setup?.();
        sidebar.render(document.querySelector('#sidebar'));
    });
    const workbench = page.locator('.hutx-workbench');
    assert.equal(await workbench.locator('.wb-page-context').getAttribute('aria-label'),'生成、试听并采用口播');
    assert.equal(await workbench.locator('.wb-page-heading,.wb-description').count(),0);
    await workbench.getByRole('button',{name:'添加三角色口播',exact:true}).click();
    await workbench.locator('[data-role=A] [data-field=text]').fill('你好，这是工作台的第一段台词。');
    await workbench.locator('[data-role=A] [data-field=text]').dispatchEvent('input');
    assert.equal(await page.evaluate(()=>JSON.parse(app.graph._nodes[0].widgets.find(w=>w.name==='role_A').value).text), '你好，这是工作台的第一段台词。');
    await workbench.locator('[data-role=A]').getByRole('button',{name:'生成测试音',exact:true}).click();
    await workbench.locator('[data-role=A]').getByRole('button',{name:'采用此音频',exact:true}).click();
    await page.waitForFunction(()=>JSON.parse(app.graph._nodes[0].widgets.find(w=>w.name==='role_A').value).adopted_audio_file);
    const panelId = await page.evaluate(()=>{const root=app.graph._nodes[0].hutxWorkbenchPanel.root;root.dataset.identity='canonical';return root.dataset.identity;});
    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    assert.equal(await workbench.locator('.wb-page-context').getAttribute('aria-label'),'设置素材与提示词，生成镜头');
    assert.equal(await page.locator('#canvas [data-identity=canonical]').count(),1);
    await workbench.getByRole('button',{name:'添加基础单采线路',exact:true}).click();
    await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).fill('<Picture 1> 中的人物自然说话。');
    await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).dispatchEvent('input');
    // Canvas virtualization must never own/remove the editor leased by the sidebar.
    await page.evaluate(()=>{
        const node=app.graph._nodes.find(node=>node.type==='GHLocalVideoInputDualEngineGH'),panel=node.hutxWorkbenchPanel;
        globalThis.originalVideoEditor=panel.element;globalThis.originalVideoCanvasParent=panel.canvasHost.parentElement;
        panel.element.dataset.identity='video-canonical';
        panel.canvasHost.remove();
    });
    assert.equal(await workbench.locator('[data-identity=video-canonical]').count(),1);
    assert.equal(await page.evaluate(()=>app.graph._nodes.find(n=>n.type==='GHLocalVideoInputDualEngineGH').hutxWorkbenchPanel.element===originalVideoEditor),true);
    // A lost placeholder + detached renderer host used to remove the editor permanently.
    await page.evaluate(()=>app.graph._nodes.find(n=>n.type==='GHLocalVideoInputDualEngineGH').hutxWorkbenchPanel.canvasHost.querySelector('.hutx-workbench-placeholder')?.remove());
    await workbench.getByRole('tab',{name:/角色与声音/}).click();
    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).waitFor();
    assert.equal(await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).inputValue(),'<Picture 1> 中的人物自然说话。');
    await workbench.getByRole('button',{name:'定位节点',exact:true}).click();
    await workbench.getByRole('button',{name:'在工作台编辑',exact:true}).click();
    await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).waitFor();
    // Also recover a legacy renderer that has detached the editor itself.
    await page.evaluate(()=>originalVideoEditor.remove());
    await page.waitForFunction(()=>document.querySelector('.hutx-workbench [data-identity=video-canonical]'));
    assert.equal(await page.evaluate(()=>app.graph._nodes.find(n=>n.type==='GHLocalVideoInputDualEngineGH').hutxWorkbenchPanel.element===originalVideoEditor),true);
    await page.evaluate(()=>originalVideoCanvasParent.append(app.graph._nodes.find(n=>n.type==='GHLocalVideoInputDualEngineGH').hutxWorkbenchPanel.canvasHost));
    await workbench.getByRole('tab',{name:/角色与声音/}).click();
    assert.equal(await workbench.locator('[data-identity='+panelId+']').count(),1);
    await workbench.getByRole('button',{name:'连接到当前镜头三槽音频',exact:true}).click();
    assert.equal(await page.evaluate(()=>app.graph._nodes.find(n=>n.type==='GHLocalVideoInputDualEngineGH').inputs.filter(i=>/^reference_audio_/.test(i.name)&&i.link!=null).length),3);
    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    assert.equal(await workbench.getByRole('checkbox',{name:'二采精修',exact:true}).isDisabled(),true);
    assert.equal(await workbench.locator('.wb-bottom .wb-refinements').count(),1);
    assert.equal(await workbench.locator('.wb-content .wb-refinements').count(),0);
    await page.evaluate(()=>{
        const graph=app.graph,sampler=graph._nodes.find(n=>n.type==='SamplerCustomAdvanced'),decode=graph._nodes.find(n=>n.type==='MiniMaxH3AVDecodeT8GH'),video=graph._nodes.find(n=>n.type==='CreateVideo');
        const add=(title,upstream,target,input)=>{
            const node=LiteGraph.createNode('ComfySwitchNode');node.title=title;graph.add(node);
            const index=target.inputs.findIndex(item=>item.name===input);target.disconnectInput(index);
            upstream.connect(0,node,0);upstream.connect(0,node,1);node.connect(0,target,index);return node;
        };
        globalThis.secondSwitch=add('二采开关',sampler,decode,'av_latent');
        globalThis.faceSwitch=add('VOSR2 修脸开关',decode,video,'images');
        globalThis.switchLinks=JSON.stringify(graph.links);
    });
    await page.waitForFunction(()=>document.querySelector('[data-branch=second]')?.disabled===false);
    await workbench.getByRole('checkbox',{name:'二采精修',exact:true}).uncheck();
    assert.equal(await page.evaluate(()=>secondSwitch.widgets[0].value),false);
    assert.equal(await page.evaluate(()=>faceSwitch.widgets[0].value),true);
    await workbench.getByRole('checkbox',{name:'VOSR2 修脸',exact:true}).uncheck();
    assert.equal(await page.evaluate(()=>faceSwitch.widgets[0].value),false);
    await page.evaluate(()=>{faceSwitch.widgets[0].value=true;});
    await page.waitForFunction(()=>document.querySelector('[data-branch=face]')?.checked===true);
    assert.equal(await page.evaluate(()=>JSON.stringify(app.graph.links)===switchLinks),true);
    assert.equal(await page.evaluate(()=>sidebar.title),'HuTX总台');
    await workbench.getByRole('button',{name:'运行当前画布',exact:true}).click();
    await page.waitForFunction(()=>globalThis.queued===1);
    assert.equal(await workbench.getByRole('tab',{name:/成片管理/}).getAttribute('aria-selected'),'true');
    assert.equal(await workbench.locator('.wb-page-context').getAttribute('aria-label'),'预览、下载和整理成片');
    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    assert.equal(await workbench.locator('.wb-bottom [data-action=generate]').count(),1);
    assert.equal(await workbench.locator('.wb-content [data-action=generate]').count(),0);
    assert.match(await workbench.locator('.wb-progress-title').innerText(),/等待队列/);
    await page.evaluate(()=>{
        globalThis.queueSnapshot={queue_running:[[0,'ui-progress',{}]],queue_pending:[]};
        testEvents.dispatchEvent(new CustomEvent('execution_start',{detail:{prompt_id:'ui-progress'}}));
        const sampler=app.graph._nodes.find(node=>node.type==='SamplerCustomAdvanced');
        testEvents.dispatchEvent(new CustomEvent('executing',{detail:String(sampler.id)}));
        testEvents.dispatchEvent(new CustomEvent('progress_state',{detail:{prompt_id:'ui-progress',nodes:{[sampler.id]:{state:'running',value:2,max:4,node_id:String(sampler.id)}}}}));
    });
    assert.equal(await workbench.locator('.wb-progress-bar').evaluate(node=>node.value),50);
    assert.match(await workbench.locator('.wb-progress-detail').innerText(),/2 \/ 4 · 50%/);
    await workbench.getByRole('button',{name:'展开',exact:true}).click();
    await workbench.getByRole('button',{name:'HyperFlow · 8-Step',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-summary=generation]')?.textContent.includes('HyperFlow'));
    assert.equal(await workbench.getByRole('checkbox',{name:'二采精修',exact:true}).isChecked(),false);
    assert.equal(await workbench.getByRole('checkbox',{name:'VOSR2 修脸',exact:true}).isChecked(),false);
    assert.equal(await workbench.getByRole('checkbox',{name:'二采精修',exact:true}).isDisabled(),true);

    const toolbarGeometry=await workbench.locator('.wb-toolbar-generation').evaluate(toolbar=>{
        const select=toolbar.querySelector('select').getBoundingClientRect(),locate=toolbar.querySelector('button').getBoundingClientRect(),meta=toolbar.querySelector('.wb-node-meta').getBoundingClientRect();
        return {select:select.width,locateRight:locate.right,metaLeft:meta.left,selectBottom:select.bottom,metaBottom:meta.bottom};
    });
    assert(toolbarGeometry.select<=441&&toolbarGeometry.metaLeft>toolbarGeometry.locateRight);
    assert(Math.abs(toolbarGeometry.selectBottom-toolbarGeometry.metaBottom)<2);
    await page.screenshot({path:path.join(out,'generation-progress-wide.png')});
    await workbench.locator('.wb-content').evaluate(node=>node.scrollTop=node.scrollHeight);
    assert.equal(await workbench.locator('.wb-bottom [data-action=generate]').evaluate(node=>{const box=node.getBoundingClientRect();return box.top>=0&&box.bottom<=innerHeight;}),true);
    await workbench.getByRole('button',{name:'Fused Turbo · 4-Step',exact:true}).click();
    await workbench.getByRole('button',{name:'收起',exact:true}).click();
    await page.evaluate(()=>{
        testEvents.dispatchEvent(new CustomEvent('execution_success',{detail:{prompt_id:'another-task'}}));
        testEvents.dispatchEvent(new CustomEvent('progress',{detail:{prompt_id:'ui-progress',value:4,max:4}}));
    });
    assert.equal(await workbench.locator('.wb-execution-progress').getAttribute('data-state'),'running');
    await page.evaluate(()=>testEvents.dispatchEvent(new CustomEvent('executing',{detail:'final-decode'})));
    assert.equal(await workbench.locator('.wb-progress-bar').getAttribute('value'),null);
    await page.evaluate(()=>{queueSnapshot={queue_running:[],queue_pending:[]};queueHistory['ui-progress']={status:{completed:true,status_str:'success'}};testEvents.dispatchEvent(new CustomEvent('execution_success',{detail:{prompt_id:'ui-progress'}}));});
    assert.equal(await workbench.locator('.wb-progress-bar').evaluate(node=>node.value),100);
    assert.match(await workbench.locator('.wb-progress-title').innerText(),/任务已完成/);
    assert.equal(await page.evaluate(()=>testCalls.filter(url=>url.endsWith('/generate')).length),1);
    await workbench.getByRole('tab',{name:/成片管理/}).click();
    await workbench.getByRole('button',{name:'选入待拼接',exact:true}).click();
    assert.equal(await page.evaluate(()=>app.graph.extra.hutx_workbench.shortlist.length),1);
    const previewSize=await workbench.locator('.wb-video-card video').first().boundingBox();
    assert(previewSize.width<=321&&previewSize.height<=261);
    await workbench.locator('.wb-result-list').screenshot({path:path.join(out,'compact-history-preview.png')});

    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    await workbench.getByRole('button',{name:'将当前设置保存为镜头',exact:true}).click();
    await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).fill('<Picture 1> 中的人物向右转身。');
    await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).dispatchEvent('input');
    await workbench.getByRole('button',{name:'将当前设置保存为镜头',exact:true}).click();
    await workbench.getByRole('button',{name:'逐段生成未完成镜头',exact:true}).click();
    await page.waitForFunction(()=>app.graph.extra.hutx_workbench.shots.filter(s=>s.state==='complete').length===2);
    assert.equal(await page.evaluate(()=>batchPayloads.length),2);
    const batchPrompts=await page.evaluate(()=>batchPayloads.map(p=>Object.values(p.output).find(n=>n.class_type==='GHLocalVideoInputDualEngineGH').inputs.prompt));
    assert.notEqual(batchPrompts[0],batchPrompts[1]);
    await page.screenshot({path:path.join(out,'shots-sequence.png')});
    for(let index=0;index<2;index++){
        await workbench.locator('.wb-shot').nth(index).locator('summary').click();
        await workbench.locator('.wb-shot').nth(index).getByRole('button',{name:'选入成片',exact:true}).click();
    }
    await workbench.getByRole('tab',{name:/成片管理/}).click();
    // Stage 3: edits are per clip, survive reordering and reach assembly unchanged.
    const editor=()=>workbench.locator('.wb-clip').first();
    await editor().locator('summary').click();
    if(process.env.HUTX_TEST_VIDEO){
        await page.waitForFunction(()=>document.querySelector('.wb-clip video')?.duration===2);
        assert.match(await workbench.locator('.wb-duration-summary').innerText(),/0:06.00/);
    }
    await editor().getByRole('spinbutton',{name:'片段 1 入点（秒）',exact:true}).fill('0.25');
    await editor().getByRole('spinbutton',{name:'片段 1 入点（秒）',exact:true}).press('Tab');
    await editor().getByRole('spinbutton',{name:'片段 1 出点（秒）',exact:true}).fill('1.25');
    await editor().getByRole('spinbutton',{name:'片段 1 出点（秒）',exact:true}).press('Tab');
    await editor().getByRole('spinbutton',{name:'片段 1 音量（%）',exact:true}).fill('40');
    await editor().getByRole('spinbutton',{name:'片段 1 音量（%）',exact:true}).press('Tab');
    await editor().getByRole('checkbox',{name:'片段 1 静音',exact:true}).check();
    assert.deepEqual(await page.evaluate(()=>app.graph.extra.hutx_workbench.shortlist[0].edit),{trim_start:.25,trim_end:1.25,volume:.4,muted:true});
    if(process.env.HUTX_TEST_VIDEO){
        await page.waitForFunction(()=>document.querySelector('.wb-clip video')?.readyState>=2);
        await editor().getByRole('button',{name:'播放选段',exact:true}).click();
        await page.waitForFunction(()=>{const video=document.querySelector('.wb-clip video');return video.paused&&video.currentTime>=1.25;});
        assert.equal(await editor().locator('video').evaluate(video=>video.muted),true);
    }
    // Invalid pending text must not export the last valid settings silently.
    await editor().getByRole('spinbutton',{name:'片段 1 出点（秒）',exact:true}).fill('0.1');
    await editor().getByRole('spinbutton',{name:'片段 1 出点（秒）',exact:true}).press('Tab');
    await workbench.getByRole('button',{name:'拼接导出 MP4',exact:true}).click();
    assert.equal(await page.evaluate(()=>globalThis.assemblyPayload),undefined);
    await editor().getByRole('spinbutton',{name:'片段 1 出点（秒）',exact:true}).fill('1.25');
    await editor().getByRole('spinbutton',{name:'片段 1 出点（秒）',exact:true}).press('Tab');
    await workbench.getByRole('button',{name:'下移片段 1',exact:true}).click();
    assert.equal(await page.evaluate(()=>app.graph.extra.hutx_workbench.shortlist[1].edit.muted),true);
    await workbench.getByRole('button',{name:'上移片段 2',exact:true}).click();
    if(process.env.HUTX_TEST_VIDEO)await page.waitForFunction(()=>document.querySelector('.wb-clip video')?.readyState>=2);
    await page.screenshot({path:path.join(out,'clip-editing.png')});
    await workbench.getByRole('button',{name:'拼接导出 MP4',exact:true}).click();
    assert.equal(await editor().getByRole('spinbutton',{name:'片段 1 入点（秒）',exact:true}).isDisabled(),true);
    await workbench.getByRole('link',{name:'下载拼接成片',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>assemblyPayload.clips.length),3);
    assert.deepEqual(await page.evaluate(()=>assemblyPayload.clips[0].edit),{trim_start:.25,trim_end:1.25,volume:.4,muted:true});
    // A later edit invalidates the old assembled result and never changes its file.
    await editor().getByRole('button',{name:'重置编辑',exact:true}).click();
    assert.equal(await workbench.getByRole('link',{name:'下载拼接成片',exact:true}).count(),0);
    assert.deepEqual(await page.evaluate(()=>app.graph.extra.hutx_workbench.shortlist[0].edit),{trim_start:0,trim_end:null,volume:1,muted:false});
    await page.screenshot({path:path.join(out,'assembly-result.png')});
    await workbench.getByRole('textbox',{name:'项目名称',exact:true}).fill('HuTX 第一版测试');
    await workbench.getByRole('textbox',{name:'项目名称',exact:true}).press('Tab');
    await workbench.getByRole('button',{name:'展开',exact:true}).click();
    await page.screenshot({path:path.join(out,'results-wide.png')});
    await workbench.getByRole('tab',{name:/角色与声音/}).click();
    assert.match(await workbench.getByRole('combobox',{name:'选择口播节点',exact:true}).innerText(),/HuTX_多角色口播/);
    await page.evaluate(()=>{
        globalThis.singleSpeechOption={type:'GHSpeechInputGH',title:'Old speech node',pos:[0,0],size:[400,600],inputs:[],outputs:[],widgets:[]};app.graph.add(singleSpeechOption);
    });
    await page.waitForFunction(()=>document.querySelector('[aria-label="选择口播节点"]')?.textContent.includes('HuTX_单角色口播'));
    await page.evaluate(()=>app.graph.remove(singleSpeechOption));
    await page.screenshot({path:path.join(out,'roles-wide.png')});
    await workbench.getByRole('button',{name:'收起',exact:true}).click();
    await page.screenshot({path:path.join(out,'roles-sidebar.png')});
    // Closing the native sidebar must restore the exact original editor without discarding adoption.
    await page.locator('#sidebar').evaluate(node=>node.style.display='none');
    await page.waitForFunction(()=>document.querySelector('#canvas [data-identity=canonical]'));
    await page.locator('#sidebar').evaluate(node=>node.style.display='');
    await page.waitForFunction(()=>document.querySelector('.hutx-workbench [data-identity=canonical]'));
    assert(await page.evaluate(()=>JSON.parse(app.graph._nodes[0].widgets.find(w=>w.name==='role_A').value).adopted_audio_file));
    await page.locator('#sidebar').evaluate(node=>node.style.width='360px');
    assert(await workbench.locator('.wb-content').evaluate(node=>node.scrollWidth<=node.clientWidth+2));
    await page.screenshot({path:path.join(out,'roles-narrow.png')});
    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    await page.evaluate(async()=>{
        const {createCloudPromptHistory}=await import('/web/js/gh_video_input_shared.js');
        const textarea=document.createElement('textarea');textarea.value='Before';
        globalThis.promptHeaderFixture=createCloudPromptHistory({textarea,label:(en,zh)=>zh,initialState:{original_prompt:'Before',optimized_prompt:'After'},onApply:value=>textarea.value=value});
        promptHeaderFixture.element.dataset.headerFixture='';document.querySelector('.wb-content').prepend(promptHeaderFixture.element);
    });
    const headerFixture=workbench.locator('[data-header-fixture]');
    await headerFixture.getByRole('button',{name:'使用优化结果',exact:true}).click();assert.equal(await headerFixture.locator('textarea').first().inputValue(),'After');
    await headerFixture.getByRole('button',{name:'恢复原始提示词',exact:true}).click();assert.equal(await headerFixture.locator('textarea').first().inputValue(),'Before');
    const headerPosition=await headerFixture.evaluate(root=>({header:root.querySelector('.gh-prompt-header').getBoundingClientRect().bottom,text:root.querySelector('textarea').getBoundingClientRect().top}));
    assert(headerPosition.header<=headerPosition.text);
    await headerFixture.evaluate(node=>node.remove());
    // The configuration portal should remain readable and usable with the workbench skin.
    await workbench.getByRole('button',{name:/LLM提示词优化配置/}).click();
    const optimizerDialog=page.locator('.gh-opt-dialog');await optimizerDialog.waitFor();
    await optimizerDialog.screenshot({path:path.join(out,'workbench-optimizer-dialog.png')});
    await optimizerDialog.getByRole('button',{name:'取消',exact:true}).click();
    if(process.env.HUTX_LAYOUT_AUDIT)await auditWorkbenchLayout(page,out,{strict:process.env.HUTX_LAYOUT_AUDIT!=='report'});
    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    assert.equal(await workbench.getByRole('button',{name:'前往角色与声音',exact:true}).count(),0);
    await workbench.getByRole('tab',{name:/成片管理/}).click();
    const deletionCard=()=>workbench.locator('.wb-video-card').filter({has:page.getByText('test.mp4',{exact:true})});
    const beforeDeletion=await workbench.locator('.wb-video-card').count();
    await deletionCard().getByRole('button',{name:'删除',exact:true}).click();
    assert.equal(await page.evaluate(()=>globalThis.deletePayload),undefined);
    await deletionCard().getByRole('button',{name:'取消',exact:true}).click();
    assert.equal(await deletionCard().getByRole('button',{name:'确认删除',exact:true}).count(),0);
    await page.evaluate(()=>globalThis.failDelete=true);
    await deletionCard().getByRole('button',{name:'删除',exact:true}).click();
    await deletionCard().getByRole('button',{name:'确认删除',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.wb-status')?.textContent.includes('被占用'));
    assert.equal(await workbench.locator('.wb-video-card').count(),beforeDeletion);
    assert(await page.evaluate(()=>app.graph.extra.hutx_workbench.shortlist.some(file=>file.filename==='test.mp4')));
    await page.evaluate(()=>globalThis.failDelete=false);
    await deletionCard().getByRole('button',{name:'删除',exact:true}).click();
    await deletionCard().getByRole('button',{name:'确认删除',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('.wb-video-card video[aria-label="test.mp4"]'));
    assert.equal(await workbench.locator('.wb-video-card').count(),beforeDeletion-1);
    assert.equal(await page.evaluate(()=>app.graph.extra.hutx_workbench.shortlist.some(file=>file.filename==='test.mp4')),false);
    await workbench.getByRole('button',{name:'刷新',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.wb-result-summary h3')?.textContent.endsWith('2'));
    assert.equal(await deletionCard().count(),0);
    const completedShot=await page.evaluate(()=>app.graph.extra.hutx_workbench.shots.find(shot=>shot.state==='complete'&&shot.results.length));
    const shotCard=workbench.locator('.wb-video-card').filter({has:page.getByText(completedShot.results[0].filename,{exact:true})});
    await shotCard.getByRole('button',{name:'删除',exact:true}).click();
    await shotCard.getByRole('button',{name:'确认删除',exact:true}).click();
    await page.waitForFunction(id=>app.graph.extra.hutx_workbench.shots.find(shot=>shot.id===id).state==='draft',completedShot.id);
    assert.deepEqual(await page.evaluate(id=>app.graph.extra.hutx_workbench.shots.find(shot=>shot.id===id).results,completedShot.id),[]);
    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    // Missed WebSocket start: the backend queue still proves that inference is running.
    await page.evaluate(()=>{queueSnapshot={queue_running:[[5,'rest-recovered',{}]],queue_pending:[[6,'pending-copy',{}]]};});
    await page.waitForFunction(()=>document.querySelector('.wb-progress-title')?.textContent.includes('后端任务正在执行'));
    assert.equal(await workbench.locator('.wb-bottom [data-action=generate]').isDisabled(),true);
    assert.match(await workbench.locator('.wb-bottom [data-action=generate]').innerText(),/执行中/);
    await page.screenshot({path:path.join(out,'queue-recovered-without-websocket.png')});
    await page.evaluate(()=>{
        queueSnapshot={queue_running:[],queue_pending:[]};
        queueHistory['rest-recovered']={status:{status_str:'error',completed:true,messages:[['execution_error',{exception_message:'cuBLAS handle creation error: 1'}]]}};
    });
    await page.waitForFunction(()=>document.querySelector('.wb-status')?.textContent.includes('cuBLAS'));
    assert.equal(await workbench.locator('.wb-execution-progress').getAttribute('data-state'),'error');
    assert.equal(await workbench.locator('.wb-bottom [data-action=generate]').isDisabled(),false);
    await page.evaluate(()=>{app.queuePrompt=async()=>false;});
    await workbench.getByRole('button',{name:'运行当前画布',exact:true}).click();
    await page.waitForSelector('.wb-status[data-state=error]');
    assert.match(await workbench.locator('.wb-status').innerText(),/未接受/);
    // Switching workflows releases the old panel and does not copy its private state to the new graph.
    await page.evaluate(()=>{app.graph=makeGraph();});
    await page.waitForSelector('.wb-empty');
    assert.equal(await page.evaluate(()=>app.graph._nodes.length),0);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(out,'verification.txt'),'PASS: canonical panels, adoption, three-slot wiring, starter graph, queue, history, shortlist, sidebar close and workflow switch.\n');
    console.log('PASS: workbench browser integration; no real providers or model queue');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
