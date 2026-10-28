// Opt-in: real isolated ComfyUI frontend + real model directory lists; no Queue/LLM.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.HUTX_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/,'$1')),'..');
const stage6=process.env.HUTX_LOCAL_SMOKE_RELEASE==='v040';
const out=path.join(root,'.test-artifacts',stage6?'local-v040':'local-v031');fs.mkdirSync(out,{recursive:true});
const graph=JSON.parse(fs.readFileSync(path.join(root,'.local-smoke-v030/user/default/workflows/V030 Local UI Fixture.json'),'utf8'));
graph.nodes=graph.nodes.slice(0,1);graph.nodes[0].pos=[30,50];graph.nodes[0].size=[560,950];
graph.nodes[0].properties.gh_local_video_state=JSON.stringify({schema_version:1,mode:'text_keyframes',prompt:'Use <Picture 1>',media:[['first_frame',{name:'01.png',kind:'image'}]],optimizer:{config:{provider:'dashscope',read_media:false},original_prompt:'Original <Picture 1>',optimized_prompt:'Optimized <Picture 1>'}});
if(stage6)graph.nodes[0].properties.gh_local_video_state=graph.nodes[0].properties.gh_local_video_state.replace('01.png','person.png');
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
 const page=await browser.newPage({viewport:{width:1500,height:1150}}),errors=[];
 page.on('pageerror',e=>{errors.push(e.message);console.error('PAGE ERROR: '+e.message);});
 page.on('console',message=>{if(message.type()==='error')console.error('BROWSER: '+message.text());});
 await page.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.hostname!=='127.0.0.1')return route.abort();
  if(url.pathname.endsWith('/prompt')||url.pathname.includes('/prompt-optimizer/optimize'))return route.abort();
  return route.continue();
 });
 await page.goto('http://127.0.0.1:8190',{waitUntil:'networkidle'});
 await page.waitForFunction(()=>window.app?.graph,{timeout:60000});
 await page.evaluate(async graph=>{await window.app.loadGraphData(graph);window.app.canvas.ds.scale=1;window.app.canvas.ds.offset=[100,0];window.app.canvas.setDirty(true,true);},graph);
 await page.waitForSelector('.gh-local-video-root',{timeout:15000}).catch(async error=>{
  await page.screenshot({path:path.join(out,'real-comfy-mount-failure.png')});
  console.log(JSON.stringify(await page.evaluate(()=>({text:document.body.innerText.slice(-5000),nodes:app.graph._nodes.map(n=>({type:n.type,widgets:n.widgets?.map(w=>({name:w.name,hidden:w.hidden,element:!!w.element})),size:n.size,pos:n.pos})),roots:[...document.querySelectorAll('.gh-local-video-root')].map(r=>({rect:r.getBoundingClientRect().toJSON(),html:r.outerHTML.slice(0,500)}))}))));throw error;
 });
 await page.waitForFunction(()=>document.querySelector('.gh-local-video-root .gh-cloud-prompt').value==='Use <Picture 1>');
 const records=[];
 if(stage6){
  await page.evaluate(()=>document.querySelector('[data-driver]').closest('details').open=true);
  await page.locator('[data-driver="driver_model_family"]').selectOption('FL2VA');
  await page.locator('[data-driver="driver_conflict"]').selectOption('use_connected_audio');
  await page.locator('[data-driver="driver_slot"]').selectOption('hybrid_audio');
 }
 for(const width of [380,460,560,720,900]) {
  await page.evaluate(width=>{const node=app.graph._nodes.find(n=>n.type==='GHLocalVideoInputGH');node.setSize([width,950]);app.canvas.setDirty(true,true);},width);
  await page.waitForFunction(width=>{const r=document.querySelector('.gh-local-video-root').getBoundingClientRect();return Math.abs(r.width-(width-20))<2;},width);
  const record=await page.evaluate(()=>{const node=app.graph._nodes.find(n=>n.type==='GHLocalVideoInputGH'),root=document.querySelector('.gh-local-video-root'),host=root.closest('.dom-widget')||root.parentElement;return {node:node.size[0],host:host.getBoundingClientRect().width,root:root.getBoundingClientRect().width,overflow:root.scrollWidth>root.clientWidth+1,options:[...root.querySelectorAll('.gh-local-config select')].map(s=>({selected:s.value,count:s.options.length}))};});
  assert.equal(record.node,width);assert.ok(Math.abs(record.host-record.root)<2);assert.equal(record.overflow,false);assert.ok(record.options.every(s=>s.count>0&&s.selected));
  records.push(record);
 }
 // Real serialization, full page reload, then load the saved graph in a fresh UI.
 const saved=await page.evaluate(()=>app.graph.serialize());
 if(stage6)console.log(JSON.stringify({savedWidgetCount:saved.nodes[0].widgets_values?.length,driverSaved:saved.nodes[0].widgets_values?.slice(28,31)}));
 if(stage6)console.log(JSON.stringify(await page.evaluate(()=>({driverWidgets:app.graph._nodes[0].widgets.map((w,i)=>({name:w.name,index:i,value:w.name.startsWith('driver_')?w.value:undefined})),savedDriverValues:app.graph._nodes[0].widgets.filter(w=>w.name.startsWith('driver_')).map(w=>w.value)}))));
 const state=JSON.parse(saved.nodes[0].properties.gh_local_video_state);assert.equal(state.optimizer.original_prompt,'Original <Picture 1>');
 await page.reload({waitUntil:'networkidle'});await page.waitForFunction(()=>window.app?.graph,{timeout:60000});
 await page.evaluate(async saved=>{await app.loadGraphData(saved);app.canvas.ds.scale=1;app.canvas.ds.offset=[100,0];app.canvas.setDirty(true,true);},saved);
 await page.waitForFunction(()=>document.querySelector('.gh-local-video-root .gh-cloud-prompt')?.value==='Use <Picture 1>');
 const restored=await page.evaluate(()=>JSON.parse(app.graph.serialize().nodes[0].properties.gh_local_video_state));
 assert.equal(restored.optimizer.original_prompt,'Original <Picture 1>');assert.equal(restored.optimizer.optimized_prompt,'Optimized <Picture 1>');
 if(stage6){
  console.log(JSON.stringify(await page.evaluate(()=>({restoredDriver:app.graph._nodes[0].widgets.filter(w=>w.name.startsWith('driver_')).map(w=>({name:w.name,value:w.value})),ui:[...document.querySelectorAll('[data-driver]')].map(e=>({name:e.dataset.driver,value:e.value}))}))));
  assert.equal(await page.locator('[data-driver="driver_model_family"]').inputValue(),'FL2VA');
  assert.equal(await page.locator('[data-driver="driver_conflict"]').inputValue(),'use_connected_audio');
  assert.equal(await page.locator('[data-driver="driver_slot"]').inputValue(),'hybrid_audio');
 }
 await page.screenshot({path:path.join(out,'real-comfy-reloaded.png')});
 const result={records,historyReload:true,errors};fs.writeFileSync(path.join(out,'real-comfy-audit.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify(result));assert.deepEqual(errors,[]);
}finally{await browser.close();}
