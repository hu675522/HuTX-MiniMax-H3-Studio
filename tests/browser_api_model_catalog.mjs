import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const {chromium}=createRequire(import.meta.url)(process.env.HUTX_PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.join(root,'.test-artifacts/api-model-catalog');fs.mkdirSync(out,{recursive:true});
const mocks=`
export const extensions=[];
export const app={graph:{_nodes:[],links:{},setDirtyCanvas(){}},canvas:{ds:{scale:1}},extensionManager:{setting:{get:()=> 'zh'}},registerExtension(e){extensions.push(e);},async queuePrompt(){throw Error('Generation forbidden');}};
globalThis.app=app;globalThis.catalogCalls=[];globalThis.saved=null;
export const api={addEventListener(){},removeEventListener(){},apiURL:p=>p,async fetchApi(url,options={}){
 let data={}; const provider=new URL(url,'http://mock').searchParams.get('provider');
 if(url.endsWith('/config'))data={mode:'api',provider:'dashscope',model:'qwen-vl-max',read_media:true,models:[],mmproj_models:[],runninghub_models:[],runninghub_overseas_models:[]};
 else if(url.includes('/credential?'))data={provider,configured:true,active_source:'persisted',persisted_configured:true,persistence_supported:true};
 else if(url.includes('/api-models?')){catalogCalls.push(provider);data={provider,source:'api',models:[{id:'qwen3-vl-plus',vision:null},{id:'vision-test',vision:true},{id:'text-model',vision:false}]};}
 else if(url.endsWith('/models'))data={models:[],mmproj_models:[]};
 else throw Error('Unexpected API operation: '+url);
 return new Response(JSON.stringify(data),{status:200});
}};
`;
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1');
 if(url.pathname==='/scripts/app.js'||url.pathname==='/scripts/api.js'){res.setHeader('Content-Type','text/javascript');return res.end('export * from "/mocks.js";');}
 if(url.pathname==='/mocks.js'){res.setHeader('Content-Type','text/javascript');return res.end(mocks);}
 if(url.pathname.startsWith('/web/js/')&&/^[a-z0-9_]+\.js$/.test(url.pathname.split('/').at(-1))){res.setHeader('Content-Type','text/javascript');return res.end(fs.readFileSync(path.join(root,url.pathname)));}
 if(url.pathname==='/'){res.setHeader('Content-Type','text/html');return res.end('<body style="background:#20303e;color:white;font:12px Segoe UI"><main id="fixture"></main></body>');}
 res.statusCode=404;res.end('not found');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1000,height:850}}),errors=[],alerts=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('dialog',async dialog=>{alerts.push(dialog.message());await dialog.dismiss();});
 await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
 await page.goto('http://127.0.0.1:'+server.address().port);
 await page.evaluate(async()=>{
  await import('/web/js/studio_theme.js');
  const {createPromptOptimizerController}=await import('/web/js/prompt_optimizer_shared.js');
  const {api,app}=await import('/mocks.js');
  globalThis.controller=createPromptOptimizerController({api,app,node:{graph:app.graph},label:(en,zh)=>zh,getTask:()=> 'ref2v',getPrompt:()=> 'Test prompt',onStateChange:state=>globalThis.saved=state});
  document.querySelector('#fixture').append(controller.element);
 });
 await page.locator('.gh-opt-configure').click();
 await page.locator('.gh-opt-model-status').filter({hasText:'请重新选择'}).waitFor();
 await page.locator('.gh-opt-actions button').last().click();assert.match(alerts.pop(),/有效模型/);
 await page.locator('.gh-opt-model-search').fill('vision');
 assert.equal(await page.locator('.gh-opt-model-select option').count(),2);
 await page.locator('.gh-opt-model-select').selectOption('vision-test');
 for(const viewport of [{width:1000,height:850},{width:480,height:640},{width:360,height:640}]){
  await page.setViewportSize(viewport);
  const bounds=await page.locator('.gh-opt-dialog').evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,client:el.clientWidth,scroll:el.scrollWidth};});
  assert.ok(bounds.left>=0&&bounds.right<=viewport.width&&bounds.top>=0&&bounds.bottom<=viewport.height);
  assert.ok(bounds.scroll<=bounds.client+1,JSON.stringify(bounds));
 }
 await page.setViewportSize({width:1000,height:850});
 await page.screenshot({path:path.join(out,'shared-model-selection.png')});
 await page.locator('.gh-opt-actions button').last().click();
 assert.equal(await page.evaluate(()=>saved.config.model),'vision-test');
 assert.equal(await page.evaluate(()=>Object.hasOwn(saved.config,'models')),false);
 await page.evaluate(()=>controller.destroy());

 // The original integrated node uses the same catalogue instead of a hidden preset string.
 await page.evaluate(async()=>{
  const {extensions,app}=await import('/mocks.js');await import('/web/js/minimax_h3_integration.js');
  class Node{
   constructor(){this.id=100;this.properties={};this.inputs=[];this.outputs=[];this.widgets=[];this.size=[500,900];this.graph=app.graph;this.onNodeCreated();}
   addDOMWidget(name,type,el){document.querySelector('#fixture').append(el);return {options:{}};}
   computeSize(){return this.size;}setSize(size){this.size=size;}setDirtyCanvas(){}
  }
  await extensions.at(-1).beforeRegisterNodeDef(Node,{name:'MiniMaxH3IntegrationGH'});globalThis.originalNode=new Node();
 });
 await page.locator('.ghh3-prompt-tool').filter({hasText:'⚙'}).click();
 await page.locator('.ghh3-opt-dialog .gh-opt-model-status').filter({hasText:'请重新选择'}).waitFor();
 await page.locator('.ghh3-opt-dialog .gh-opt-model-select').selectOption('qwen3-vl-plus');
 await page.screenshot({path:path.join(out,'integrated-model-selection.png')});
 await page.locator('.ghh3-opt-actions button').last().click();
 assert.equal(await page.evaluate(()=>JSON.parse(originalNode.properties.gh_h3_state).optimizer.model),'qwen3-vl-plus');
 assert.deepEqual(errors,[]);assert.deepEqual(alerts,[]);
 console.log('PASS: shared/integrated configuration, invalid model validation, exact saved model, no catalogue persistence, 360/480/1000px layouts');
}finally{await browser.close();server.close();}
