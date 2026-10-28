// Real Edge layout and interactions, actual production UI, mock-only APIs.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.HUTX_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/,'$1')),'..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const strip=s=>s.replace(/^import[\s\S]*?from\s+["'][^"']+["'];\s*/gm,'').replace(/\bexport /g,'');
const out=path.join(root,'.test-artifacts','local-v031');fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
 const page=await browser.newPage({viewport:{width:1140,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',route=>route.abort());
 await page.setContent(`<style>body{margin:0;background:#0b141d;color:#dce8ef;font:12px Arial}.node-frame{position:fixed;box-sizing:border-box;border:1px solid #42849b;border-radius:8px;pointer-events:none}.dom-widget{position:fixed;transform-origin:0 0}.isolate{isolation:isolate}</style><div class="isolate"></div>`);
 await page.addScriptTag({content:`
const extensions=[],app={graph:{},registerExtension:e=>extensions.push(e),extensionManager:{setting:{get:()=> 'zh'}},queuePrompt:async()=>{globalThis.queueCount++;}};
globalThis.queueCount=0;globalThis.requests=[];globalThis.mode='success';
const api={fetchApi:async(url,options={})=>{
 const body=options.body?JSON.parse(await options.body.text()):null;requests.push({url,body});
 let data={},ok=true;
 if(url.includes('/local-media-info?'))data={width:1920,height:1080,has_audio:true};
 else if(url.includes('/adopted-preview?'))data={audio_file:'hutx-speech/adopted/'+ 'b'.repeat(64)+'.wav',duration_seconds:6};
 else if(url.endsWith('/config'))data={mode:'api',provider:'dashscope',read_media:false,auto_optimize:true};
 else if(url.includes('/credential?'))data={provider:'dashscope',configured:true,active_source:'persisted',persisted_configured:true};
 else if(url.endsWith('/optimize')){await new Promise(r=>setTimeout(r,350));ok=globalThis.mode!=='failure';data=ok?{prompt:body.prompt+' Smooth continuous motion.',report:'{"status":"optimized"}'}:{error:'Mock failure'};}
 else if(!url.endsWith('/cancel'))throw Error('Unexpected API '+url);
 return {ok,status:ok?200:400,json:async()=>data,text:async()=>JSON.stringify(data)};
}};globalThis.alert=()=>{};
`+['studio_theme.js','video_input_components.js','responsive_dom_host.js','gh_video_input_shared.js','prompt_optimizer_shared.js','local_video_input_state.js','local_driver_preview.js','gh_local_video_input.js','gh_cloud_video_input.js'].map(p=>strip(read('web/js/'+p))).join('\n')+`
globalThis.before=[];
const audit=node=>{const {root,host}=node.mount,chain=[];for(let e=root,i=0;e&&i<6;e=e.parentElement,i++){const s=getComputedStyle(e);chain.push({className:e.className,width:e.getBoundingClientRect().width,computedWidth:s.width,maxWidth:s.maxWidth,minWidth:s.minWidth,display:s.display,flex:s.flex,alignSelf:s.alignSelf,inline:e.getAttribute('style')});}return {node:node.frame.getBoundingClientRect().width,host:host.getBoundingClientRect().width,root:root.getBoundingClientRect().width,overflow:root.scrollWidth>root.clientWidth+1,chain};};
class FixtureNode {
 constructor(type,saved,values){this.type=type;this.graph=app.graph;this.mode=0;this.size=[720,1040];this.width=720;this.properties={};this.widgets=[];
  this.frame=document.createElement('div');this.frame.textContent=type;document.querySelector('.isolate').append(this.frame);this.frame.className='node-frame';
  const local=type==='GHLocalVideoInputGH';
  const defaults=local?{model_name:'minimax_h3_fl2va_pruned_int8_convrot.safetensors',clip_name:'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',video_vae_name:'minimax_h3_video_vae_fp16.safetensors',audio_vae_name:'minimax_h3_audio_vae_fp32.safetensors',aspect:'16:9',megapixels:0.5,duration_seconds:5,driver_model_family:'unconfirmed',driver_conflict:'reject_conflicts',driver_slot:'auto',main_mode:'text_keyframes',prompt:'Use <Picture 1>',gh_local_state_json:''}:{main_mode:'text_keyframes',prompt:'Use <Picture 1>',aspect:'16:9',duration_seconds:5,gh_cloud_state_json:'',optimizer_enabled:false,optimized_prompt:'',optimizer_report:''};
  this.widgets=Object.entries({...defaults,...values}).map(([name,value])=>({name,value,options:{values:[String(value),'alternate.safetensors']}}));
  for(const name of LOCAL_SLOTS)this.widgets.push({name,value:''});
  this.properties[local?'gh_local_video_state':'gh_cloud_video_state']=JSON.stringify(saved||{schema_version:1,mode:'text_keyframes',prompt:'Use <Picture 1>',media:[['first_frame',{name:'长文件名 Chinese duplicate 01.png',kind:'image'}]],optimizer:{config:{provider:'dashscope',read_media:false,auto_optimize:true}}});
  if(local)this.controller=createLocalVideoPanel(this);else createCloudPanel(this);
 }
 addDOMWidget(name,type,root,options){const host=document.createElement('div');host.className='dom-widget';host.append(root);document.querySelector('.isolate').append(host);const widget={name,options,width:444,margin:10};this.mount={root,host,widget};this.paint(1,false);before.push(audit(this));return widget;}
 setSize(size){this.size=size;this.width=size[0];this.mount.widget.options.afterResize?.();this.paint();}
 setDirtyCanvas(){}
 paint(scale=1,hooks=true){Object.assign(this.frame.style,{left:'24px',top:'20px',width:this.width+'px',height:'1040px',transform:'scale('+scale+')',transformOrigin:'0 0'});const {widget,host}=this.mount;if(hooks)widget.options.onDraw?.();Object.assign(host.style,{left:(24+10*scale)+'px',top:(20+35*scale)+'px',width:((widget.width??this.width)-20)+'px',height:'990px',transform:'scale('+scale+')'});}
}
globalThis.localNode=new FixtureNode('GHLocalVideoInputGH');globalThis.cloudNode=new FixtureNode('GHCloudVideoInputGH');
globalThis.show=node=>{for(const n of [localNode,cloudNode]){n.frame.hidden=n!==node;n.mount.host.hidden=n!==node;}globalThis.current=node;node.paint();};
globalThis.measure=()=>audit(current);show(localNode);
`});
 await page.waitForFunction(()=>localNode.controller && document.querySelector('.gh-local-summary').textContent.includes('960×544'));
 const widths=[];
 const driverHelp=page.getByRole('button',{name:'口播连接与时长说明',exact:true});
 await driverHelp.hover();assert.match(await page.locator('.gh-local-driver-tooltip').innerText(),/14.375/);
 await driverHelp.focus();await driverHelp.press('Escape');assert(await page.locator('.gh-local-driver-tooltip').isHidden());
 assert.equal(await page.locator('.gh-local-driver > p').filter({hasText:'将口播 AUDIO 接入'}).count(),0);
 await page.evaluate(()=>document.querySelector('[data-driver]').closest('details').open=true);
 await page.locator('[data-driver="driver_model_family"]').selectOption('FL2VA');
 await page.locator('[data-driver="driver_conflict"]').selectOption('use_connected_audio');
 await page.locator('[data-driver="driver_slot"]').selectOption('hybrid_audio');
 assert.deepEqual(await page.evaluate(()=>localNode.widgets.filter(w=>w.name.startsWith('driver_')).map(w=>w.value)),['FL2VA','use_connected_audio','hybrid_audio']);
 await page.evaluate(()=>document.querySelector('[data-driver]').closest('details').open=true);
 for(const type of ['Local','Cloud']) {
  await page.evaluate(type=>show(type==='Local'?localNode:cloudNode),type);
  for(const width of [380,460,560,720,900]) {
   await page.evaluate(width=>current.setSize([width,1040]),width);
   await page.waitForFunction(()=>Math.abs(measure().root-(current.width-20))<1);
   const record=await page.evaluate(()=>measure());assert.equal(record.node,width);assert.equal(record.host,width-20);assert.equal(record.root,width-20);assert.equal(record.overflow,false);
   widths.push({type,...record});await page.screenshot({path:path.join(out,type.toLowerCase()+'-'+width+'.png')});
   if(type==='Local'){
    const rows=await page.locator('.gh-local-driver-fields label').evaluateAll(items=>items.map(e=>e.getBoundingClientRect().top));
    assert.equal(rows.length,3);assert.ok(rows.every(y=>Math.abs(y-rows[0])<1));
   }
  }
 }
 await page.evaluate(()=>{show(localNode);localNode.setSize([560,1040]);});
 const prompt=page.locator('.gh-local-video-root .gh-cloud-prompt');
 const caretRecords=[];
 for(const [name,lines] of [['top',0],['middle',2],['bottom',5]]) {
  await prompt.fill('line\n'.repeat(lines)+'Use ');await prompt.press('End');await prompt.press('@');
  await page.waitForFunction(()=>!document.querySelector('.gh-cloud-picker').hidden);
  const record=await page.evaluate(()=>{const p=localNode.controller.prompt,c=getTextareaCaretRect(p,p.value.lastIndexOf('@')),m=document.querySelector('.gh-cloud-picker').getBoundingClientRect(),r=localNode.mount.root.getBoundingClientRect();return {caret:c,menu:m.toJSON(),root:r.toJSON()};});
  assert.ok(Math.min(Math.abs(record.menu.top-record.caret.bottom),Math.abs(record.menu.bottom-record.caret.top))<8);
  assert.ok(record.menu.left>=record.root.left-1&&record.menu.right<=record.root.right+1);caretRecords.push({name,...record});
  await page.screenshot({path:path.join(out,'caret-'+name+'.png')});await prompt.press('Escape');
 }
 await prompt.fill('中文');await prompt.press('End');await prompt.press('@');await prompt.press('Enter');await prompt.press('@');await prompt.press('Enter');
 assert.equal(await prompt.inputValue(),'中文<Picture 1><Picture 1>');
 await prompt.press('@');await page.evaluate(()=>{localNode.mount.widget.width=444;localNode.paint(.75);window.dispatchEvent(new Event('resize'));});
 await page.waitForFunction(()=>Math.abs(localNode.mount.root.getBoundingClientRect().width-405)<1);
 const zoom=await page.evaluate(()=>measure());assert.equal(zoom.root,405);
 await page.screenshot({path:path.join(out,'caret-zoom.png')});await prompt.press('Escape');
 await page.evaluate(()=>localNode.paint());await prompt.fill('Use <Picture 1>');
 await page.locator('.gh-local-video-root .gh-opt-run').click();
 assert.equal(await page.locator('.gh-local-video-root .gh-opt-timing:visible').count(),1);
 await page.waitForFunction(()=>document.querySelector('.gh-local-video-root .gh-opt-timing').dataset.state==='success');
 assert.equal(await page.locator('.gh-local-video-root .gh-opt-status').count(),0);
 await page.locator('.gh-local-video-root .gh-prompt-tabs button[value="compare"]').click();
 assert.equal(await page.locator('.gh-local-video-root .gh-prompt-readonly textarea').count(),2);
 await page.screenshot({path:path.join(out,'history-compare.png')});
 const persisted=await page.evaluate(()=>localNode.controller.serialize());assert.ok(persisted.optimizer.optimized_prompt.includes('Smooth continuous motion.'));
 await page.evaluate(()=>{const values=Object.fromEntries(localNode.widgets.map(w=>[w.name,w.value])),saved=localNode.controller.serialize();localNode.onRemoved();localNode.mount.host.remove();localNode.frame.remove();localNode=new FixtureNode('GHLocalVideoInputGH',saved,values);show(localNode);});
 assert.equal(await prompt.inputValue(),persisted.prompt);
 await page.locator('.gh-local-video-root .gh-prompt-restore').click();assert.equal(await prompt.inputValue(),'Use <Picture 1>');
 await page.evaluate(()=>{globalThis.mode='failure';});await page.locator('.gh-local-video-root .gh-opt-run').click();
 await page.waitForFunction(()=>document.querySelector('.gh-local-video-root .gh-opt-timing').dataset.state==='failure');
 await page.screenshot({path:path.join(out,'timer-failure.png')});
 await page.evaluate(()=>{globalThis.mode='success';});await page.locator('.gh-local-video-root .gh-opt-run').click();await page.locator('.gh-local-video-root .gh-opt-cancel').click();
 await page.waitForFunction(()=>!document.querySelector('.gh-local-video-root .gh-opt-run').disabled);
 assert.equal(await page.locator('.gh-local-video-root .gh-opt-timing').getAttribute('data-state'),'cancelled');
 await page.screenshot({path:path.join(out,'timer-cancelled.png')});
 // Actual Local panel: connect an adopted speech source, pick its canonical tag,
 // optimize with the same media, serialize without inventing an uploaded slot.
 await page.evaluate(()=>{
  const n=localNode;n.inputs=[{name:'driver_audio',link:9}];
  globalThis.speechSource={id:2,type:'GHSpeechInputGH',widgets:[{name:'adopted_audio_file',value:'hutx-speech/adopted/'+'a'.repeat(64)+'.json'}]};
  n.graph.links={9:{origin_id:2,origin_slot:0}};n.graph.getNodeById=()=>speechSource;
 });
 await page.waitForSelector('[data-connected-audio=true]');
 assert.equal(await page.locator('[data-connected-audio=true] audio').count(),1);
 assert.equal(await page.locator('[data-connected-audio=true] input').count(),0);
 await prompt.fill('<Picture 1>');await prompt.press('End');await prompt.press('@');
 await page.getByRole('option').filter({hasText:'已采用口播'}).click();
 assert.equal(await prompt.inputValue(),'<Picture 1><Audio 1>');
 await page.screenshot({path:path.join(out,'connected-driver-audio.png')});
 await page.locator('.gh-local-video-root .gh-opt-run').click();
 await page.waitForFunction(()=>document.querySelector('.gh-local-video-root .gh-opt-timing').dataset.state==='success');
 const payload=await page.evaluate(()=>requests.filter(r=>r.url.endsWith('/optimize')).at(-1).body);
 assert.equal(payload.task,'HYBRID');assert.ok(JSON.stringify(payload.media).includes('<Audio 1>'));
 const savedDriver=await page.evaluate(()=>localNode.controller.serialize());
 assert.equal(savedDriver.media.some(([s])=>s==='hybrid_audio'),false);
 assert.equal(JSON.stringify(savedDriver).includes('hutx-speech/adopted/'),false);
 await page.evaluate(()=>{speechSource.widgets[0].value='';});
 await page.waitForFunction(()=>!document.querySelector('[data-connected-audio=true]'));
 await prompt.fill('@');assert.equal(await page.getByRole('option').filter({hasText:'已采用口播'}).count(),0);await prompt.press('Escape');
 await page.evaluate(()=>{localNode.inputs[0].link=null;});
 await page.waitForFunction(()=>document.querySelector('.gh-local-driver-status').textContent.includes('尚未连接'));
 assert.deepEqual(errors,[]);
 const result={before:await page.evaluate(()=>before),widths,caretRecords,zoom,errors,screenshots:17};
 fs.writeFileSync(path.join(out,'audit.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify({widths:widths.map(({type,node,host,root,overflow})=>({type,node,host,root,overflow})),caret:caretRecords.map(r=>r.name),errors}));
}finally{await browser.close();}
