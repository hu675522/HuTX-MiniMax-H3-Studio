// Edge layout regression using the installed ComfyUI canvas overlay algorithm.
// Every API is mocked; root -> .dom-widget -> .isolate matches the observed live DOM.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.HUTX_PLAYWRIGHT_MODULE||'playwright');
const project=path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/,'$1')),'..');
const read=p=>fs.readFileSync(path.join(project,p),'utf8');
const strip=s=>s.replace(/^import[\s\S]*?from\s+["'][^"']+["'];\s*/gm,'').replace(/\bexport /g,'');
const browser=await chromium.launch({channel:'msedge',headless:true});
const out=path.join(project,'.test-artifacts');fs.mkdirSync(out,{recursive:true});
try {
 const page=await browser.newPage({viewport:{width:1140,height:1020}});
 await page.route('**/*',route=>route.abort());
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent(`<style>body{margin:0;background:#0b141d;font:12px Arial;color:#cde4ee}.node-frame{position:fixed;box-sizing:border-box;border:1px solid #42849b;background:#16232c;border-radius:8px;pointer-events:none}.node-title{padding:8px}.isolate{isolation:isolate}.dom-widget{position:fixed;transform-origin:0 0}.h-full{height:100%}.w-full{width:100%}</style><div class="graph-canvas-container"><div class="isolate"></div></div>`);
 await page.addScriptTag({content:`
const extensions=[];const app={graph:{},registerExtension:e=>extensions.push(e),extensionManager:{setting:{get:()=> 'zh'}},queuePrompt:async()=>{throw Error('Queue forbidden');}};
globalThis.qaCredentials={environment:false,session:false,persisted:false};globalThis.qaRequests=[];
const api={fetchApi:async (url,options={})=>{
 if(url.endsWith('/config'))return {ok:true,text:async()=>JSON.stringify({mode:'api',provider:'dashscope',read_media:false})};
 if(url.endsWith('/fal-credential')){
  const body=options.body?JSON.parse(await options.body.text()):undefined;qaRequests.push({method:options.method,body});
  if(options.method==='POST')qaCredentials[body.storage]=true;
  if(options.method==='DELETE')qaCredentials.persisted=false;
  const {environment,session,persisted}=qaCredentials;
  return {ok:true,json:async()=>({configured:environment||session||persisted,active_source:environment?'environment':session?'session':persisted?'persisted':'none',environment_configured:environment,session_configured:session,persisted_configured:persisted,persistence_supported:true})};
 }throw Error('Unexpected API');}};
`+['web/js/studio_theme.js','web/js/video_input_components.js','web/js/responsive_dom_host.js','web/js/gh_video_input_shared.js','web/js/prompt_optimizer_shared.js','web/js/gh_cloud_video_input.js','web/js/fal_credentials.js'].map(p=>strip(read(p))).join('\n')+`
const audit=(root,node)=>{const chain=[];for(let el=root,i=0;el&&i<8;el=el.parentElement,i++){const s=getComputedStyle(el);chain.push({tag:el.tagName,className:el.className,rect:el.getBoundingClientRect().toJSON(),width:s.width,maxWidth:s.maxWidth,minWidth:s.minWidth,display:s.display,flex:s.flex,alignSelf:s.alignSelf,inline:el.getAttribute('style')});}return {nodeSize:[...node.size],nodeRect:node.frame.getBoundingClientRect().toJSON(),chain};};
globalThis.qaBefore=[];
class MockNode {
 constructor(type){this.type=type;this.width=720;this.size=[720,850];this.graph=app.graph;this.mode=0;this.properties={};this.widgets=[];this.hosts=[];this.frame=document.createElement('div');this.frame.className='node-frame';this.frame.innerHTML='<div class="node-title">'+type+'</div>';document.querySelector('.isolate').append(this.frame);
 if(type==='GHCloudVideoInputGH'){this.properties.gh_cloud_video_state=JSON.stringify({mode:'all_reference',prompt:'Use <Picture 1>',aspect:'adaptive',media:[['ref_image_2',{name:'图片.png'}],['ref_video_3',{name:'Video.mp4'}]]});this.widgets=['main_mode','prompt','aspect','duration_seconds',...GH_CLOUD_MEDIA_SLOTS,'gh_cloud_state_json','optimizer_enabled','optimized_prompt','optimizer_report'].map(name=>({name,value:''}));}
 this.onNodeCreated();}
 addDOMWidget(name,type,root,options){const host=document.createElement('div');host.className='dom-widget size-full';root.classList.add('h-full','w-full');host.append(root);document.querySelector('.isolate').append(host);const widget={name,type,element:root,options,margin:10,width:444,computedHeight:820};this.widgets.push(widget);this.hosts.push({host,root,widget});this.paint(1,false);qaBefore.push(audit(root,this));return widget;}
 setSize(size){this.size=[...size];this.width=size[0];for(const {widget} of this.hosts)widget.options.afterResize?.();this.paint();}
 setDirtyCanvas(){}
 computeSize(){return this.size;}
 paint(scale=1,hooks=true){Object.assign(this.frame.style,{left:'24px',top:'20px',width:this.width+'px',height:'890px',transform:'scale('+scale+')',transformOrigin:'0 0'});
 if(hooks)this.onDrawForeground?.();
 for(const {host,widget} of this.hosts){if(hooks)widget.options.onDraw?.(widget);
 // Exact width expression from ComfyUI DomWidgets.updateWidgets.
 const width=(widget.width??this.width)-widget.margin*2;
 Object.assign(host.style,{left:(24+widget.margin*scale)+'px',top:(20+40*scale)+'px',width:width+'px',height:'810px',transform:'scale('+scale+')'});}}
}
class Cloud extends MockNode{};class Fal extends MockNode{};
for(const ext of extensions){ext.beforeRegisterNodeDef?.(Cloud,{name:'GHCloudVideoInputGH'});ext.beforeRegisterNodeDef?.(Fal,{name:'FalH3MaxVideoGH'});}
globalThis.qaCloud=new Cloud('GHCloudVideoInputGH');globalThis.qaFal=new Fal('FalH3MaxVideoGH');
globalThis.showNode=node=>{for(const n of [qaCloud,qaFal]){n.frame.hidden=n!==node;for(const h of n.hosts)h.host.hidden=n!==node;}globalThis.qaCurrent=node;node.paint();};
globalThis.auditNode=()=>audit(qaCurrent.hosts[0].root,qaCurrent);
showNode(qaCloud);
`});
 await page.waitForFunction(()=>document.querySelector('.gh-cloud-prompt').value==='Use <Picture 1>');
 const before=await page.evaluate(()=>qaBefore);
 assert.ok(before.every(b=>b.nodeSize[0]===720 && Math.abs(b.chain[1].rect.width-424)<1),'Regression fixture reproduces stale host width before binding');
 const records=[];
 for(const type of ['Cloud','Fal']) {
  await page.evaluate(type=>showNode(type==='Cloud'?qaCloud:qaFal),type);
  if(type==='Fal')await page.locator('.hutx-fal-credentials summary').click();
  else await page.locator('.gh-cloud-prompt').fill('Use @');
  for(const width of [380,460,560,720,900]) {
   await page.evaluate(width=>{qaCurrent.setSize([width,850]);},width);
   await page.waitForFunction(()=>Math.abs(qaCurrent.hosts[0].root.getBoundingClientRect().width-(qaCurrent.width-20))<1);
   const record=await page.evaluate(()=>{
    const data=auditNode(),root=qaCurrent.hosts[0].root;
    return {...data,hostRect:root.parentElement.getBoundingClientRect().toJSON(),rootRect:root.getBoundingClientRect().toJSON(),overflow:root.scrollWidth>root.clientWidth+1};
   });
   assert.equal(record.nodeRect.width,width);assert.equal(record.hostRect.width,width-20);assert.equal(record.rootRect.width,width-20);assert.equal(record.overflow,false);
   if(type==='Cloud') {
    await page.waitForFunction(()=>{const root=qaCloud.hosts[0].root.getBoundingClientRect(),menu=document.querySelector('.gh-cloud-picker').getBoundingClientRect();return menu.left>=root.left-1&&menu.right<=root.right+1;});
   }
   records.push({type,...record});
   await page.screenshot({path:path.join(out,'host-'+type.toLowerCase()+'-'+width+'.png')});
  }
  // Sidebar may assign width again. The next ComfyUI drawing pass must release it.
  await page.evaluate(()=>{qaCurrent.hosts[0].widget.width=444;qaCurrent.paint(.75);});
  const zoom=await page.evaluate(()=>auditNode());
 assert.ok(Math.abs(zoom.chain[1].rect.width-660)<1);assert.ok(Math.abs(zoom.chain[0].rect.width-660)<1);
 }
 await page.evaluate(()=>{qaFal.setSize([560,850]);qaFal.paint();});
 for(const [name,environment,session,persisted] of [['none',false,false,false],['session',false,true,false],['persisted',false,false,true],['env',true,false,false],['session-persisted',false,true,true],['env-all',true,true,true]]) {
  await page.evaluate(flags=>{qaCredentials=flags;qaFal.hosts[0].root.ontoggle();},{environment,session,persisted});
  await page.waitForFunction(()=>!document.querySelector('.hutx-fal-save').disabled);
  await page.screenshot({path:path.join(out,'credential-state-'+name+'.png')});
 }
 await page.evaluate(()=>{qaCredentials={environment:false,session:false,persisted:false};qaFal.hosts[0].root.ontoggle();});
 await page.waitForFunction(()=>!document.querySelector('.hutx-fal-save').disabled);
 await page.locator('.hutx-fal-session').click();
 assert.equal(await page.locator('.hutx-fal-feedback').getAttribute('data-kind'),'error');
 await page.screenshot({path:path.join(out,'credential-feedback-error.png')});
 await page.locator('.hutx-fal-key').fill('TEST_FAL_KEY');await page.locator('.hutx-fal-session').click();
 await page.waitForFunction(()=>document.querySelector('.hutx-fal-feedback').dataset.kind==='success');
 assert.equal(await page.locator('.hutx-fal-key').inputValue(),'');
 await page.screenshot({path:path.join(out,'credential-feedback-success.png')});
 await page.locator('.hutx-fal-key').fill('TEST_FAL_KEY');await page.locator('.hutx-fal-save').click();
 await page.waitForFunction(()=>document.querySelector('.hutx-fal-feedback').dataset.kind==='warning');
 await page.screenshot({path:path.join(out,'credential-feedback-warning.png')});
 await page.locator('.hutx-fal-delete').click();
 assert.equal(await page.locator('.hutx-fal-confirm').isVisible(),true);
 await page.screenshot({path:path.join(out,'credential-delete-confirm.png')});
 await page.locator('.hutx-fal-confirm-delete').click();
 await page.waitForFunction(()=>document.querySelector('.hutx-fal-persisted-state').textContent==='本机凭证： ○ 未保存');
 assert.equal(await page.locator('.hutx-fal-active').innerText(),'当前生效： ● 本次会话');
 await page.locator('.hutx-fal-delete').click();
 assert.equal(await page.locator('.hutx-fal-feedback').getAttribute('data-kind'),'info');
 await page.screenshot({path:path.join(out,'credential-feedback-info.png')});
 assert.ok(!(await page.locator('.hutx-fal-credentials').innerText()).includes('TEST_FAL_KEY'));
 const requests=await page.evaluate(()=>qaRequests);
 assert.equal(requests.filter(r=>JSON.stringify(r).includes('TEST_FAL_KEY')).length,2);
 assert.ok(requests.filter(r=>r.method!=='POST').every(r=>!JSON.stringify(r).includes('TEST_FAL_KEY')));
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'responsive-host-audit.json'),JSON.stringify({before,records,errors},null,2));
 console.log(JSON.stringify({before:before.map(b=>({node:b.nodeSize[0],host:b.chain[1].rect.width})),widths:records.map(r=>({type:r.type,node:r.nodeRect.width,host:r.hostRect.width,root:r.rootRect.width})),screenshots:21,credentialCombinations:6,feedbackStates:4,errors}));
}finally{await browser.close();}
