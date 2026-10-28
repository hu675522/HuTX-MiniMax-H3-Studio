// Real Edge DOM, production panel/controller, mock transport; no external calls.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.HUTX_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.join(root,'.test-artifacts','speech-stage2');fs.mkdirSync(out,{recursive:true});
const strip=s=>s.replace(/^import[^\n]*\n/gm,'').replace(/\bexport /g,'');
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
 const page=await browser.newPage({viewport:{width:1150,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const wav=Buffer.alloc(44+32000);wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(16000,24);wav.writeUInt32LE(32000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(32000,40);
 await page.route('**/*',r=>r.request().url().startsWith('http://hutx.mock/hutx/minimax-h3/speech/audio/')
    ?r.fulfill({status:200,contentType:'audio/wav',body:wav}):r.abort());
 await page.setContent('<style>body{background:#0d151c}.node{margin:20px;padding:10px;box-sizing:border-box;background:#293e4c}.dom-widget{width:100%;height:900px}</style><div class="node"><div class="dom-widget"></div></div>');
 await page.addScriptTag({content:`
 const app={registerExtension(){}};globalThis.requests=[];globalThis.behavior='success';globalThis.cancels=new Set();
 globalThis.credentialState={configured:false,active_source:'none',session_configured:false,persisted_configured:false};globalThis.errorCode=null;
 const api={apiURL:p=>'http://hutx.mock'+p,fetchApi:async(path,options={})=>{
  if(path.endsWith('/catalog'))return {ok:true,json:async()=>({credential:credentialState,engines:[{id:'local',available:false,voices:[]},{id:'cloud',available:credentialState.configured,voices:[{id:'cloud:longanyang',name:'龙安洋'},{id:'cloud:longanhuan_v3',name:'龙安欢'}]}],video_targets:[{backend:'fal',mode:'i2v',reason:'当前路由没有音频输入字段。'}]})};
  const data=JSON.parse(options.body);requests.push({path,data});
  if(path.endsWith('/credential')){credentialState={configured:true,active_source:'session',session_configured:true,persisted_configured:false};return {ok:true,json:async()=>credentialState};}
  if(path.endsWith('/adopt'))return {ok:true,json:async()=>({adopted_audio_file:'hutx-speech/adopted/'+'a'.repeat(64)+'.json'})};
  if(path.endsWith('/cancel')){cancels.add(data.request_id);return {ok:true,json:async()=>({cancelled:true})};}
  if(!path.endsWith('/generate'))throw Error('Unexpected route');
  await new Promise(r=>setTimeout(r,globalThis.mockDelay||400));
  const valid=(data.parameters.mock_demo||credentialState.configured) && data.parameters.text.trim() && (data.parameters.mode!=='clone'||data.reference_file);
  return {ok:valid&&behavior!=='error'&&!cancels.has(data.request_id),json:async()=>behavior==='error'?{code:errorCode,error:'TEST_PROVIDER_SECRET'}:({audio_id:data.request_id.replaceAll('-',''),duration_seconds:1,report:{is_mock:data.parameters.mock_demo}})};
 }};
 `+['studio_theme.js','responsive_dom_host.js','speech_controller.js','speech_input.js'].map(p=>strip(fs.readFileSync(path.join(root,'web/js',p),'utf8'))).join('\n')+`
 const values={engine:'local',mode:'preset',text:'你好，这是新台词。',reference_text:'参考录音说的是旧台词。',reference_file:'reference.wav',voice:'local:demo-a',speed:1,mock_demo:false,revision:0,adopted_audio_file:''};
 globalThis.node={widgets:Object.entries(values).map(([name,value])=>({name,value})),size:[460,900],
  addDOMWidget(name,type,element,options){document.querySelector('.dom-widget').append(element);return {options};},
  setDirtyCanvas(){},setSize(size){this.size=size;document.querySelector('.node').style.width=size[0]+'px';}};
 globalThis.panel=createSpeechPanel(node);
 `});
 const field=name=>page.locator(`[data-field="${name}"]`);
 const info=page.getByRole('button',{name:'运行环境与云端使用说明',exact:true});
 assert.equal(await info.textContent(),'?');
 await info.hover();assert(await page.getByRole('tooltip').isVisible());
 await info.focus();await info.press('Escape');assert(await page.getByRole('tooltip').isHidden());
 assert.equal(await page.locator('.hutx-speech-adopt').getAttribute('data-adopted'),'false');
 assert(await page.getByRole('button',{name:'生成口播',exact:true}).isDisabled());
 assert(await page.locator('.hutx-speech-debug').isHidden());await field('mock_demo').evaluate(e=>{e.checked=true;e.dispatchEvent(new Event('input',{bubbles:true}));});
 const records=[];
 for(const width of [380,460,560,720,900]) {
  await page.evaluate(w=>node.setSize([w,900]),width);
  const record=await page.evaluate(()=>{const n=document.querySelector('.node'),h=document.querySelector('.dom-widget'),r=panel.root;return {node:n.getBoundingClientRect().width,host:h.getBoundingClientRect().width,root:r.getBoundingClientRect().width,overflow:r.scrollWidth>r.clientWidth+1,textarea:panel.controls.text.getBoundingClientRect().width};});
  assert.equal(record.node,width);assert.equal(record.host,width-20);assert.equal(record.root,record.host);assert.equal(record.overflow,false);
  // The shared Studio skin adds intentional panel padding; the textarea fills
  // the root's content box instead of the root's border box.
  assert.equal(record.textarea,width-56);
  records.push(record);await page.screenshot({path:path.join(out,`speech-${width}.png`)});
  if(width>=560){
   const aligned=await page.evaluate(()=>{const speed=document.querySelector('[data-field=speed]').getBoundingClientRect(),buttons=[...document.querySelectorAll('.hutx-speech-actions button')].filter(e=>!e.hidden).slice(0,3);return buttons.every(b=>{const r=b.getBoundingClientRect();return Math.abs((r.top+r.bottom)-(speed.top+speed.bottom))<3;});});
   assert.equal(aligned,true);
  }
 }
 await field('engine').selectOption('cloud');
 assert.equal(await field('voice').inputValue(),'cloud:demo-a');
 await field('voice').selectOption('cloud:demo-b');
 await field('mode').selectOption('clone');assert(await field('reference_text').isHidden());assert(await field('reference_file').isHidden());assert(await field('voice').isHidden());
 await page.getByRole('textbox',{name:'参考音频名称',exact:true}).fill('我的声线');
 await page.getByRole('textbox',{name:'参考音频名称',exact:true}).press('Tab');
 assert.equal(await page.evaluate(()=>node.properties.hutx_speech_reference_name),'我的声线');
 assert.equal(await page.evaluate(()=>panel.controls.reference_file.value),'reference.wav');
 assert.equal(await page.getByRole('button',{name:'更换参考音频',exact:true}).textContent(),'↻');
 assert.equal(await page.getByRole('button',{name:'移除音频',exact:true}).textContent(),'×');
 await page.evaluate(()=>{globalThis.mockDelay=2000;const p=panel.parameters();panel.controller.generate(p,panel.controls.reference_file.value);panel.controller.generate(p,panel.controls.reference_file.value);});
 await page.waitForFunction(()=>panel.controller.state.status==='running');
 await page.waitForTimeout(180);assert(await page.evaluate(()=>panel.controller.state.elapsed>0));
 for(const width of [380,560,720]){
  const record=await page.evaluate(w=>{node.setSize([w,900]);const r=document.querySelector('.hutx-speech-actions').getBoundingClientRect(),t=document.querySelector('.hutx-speech-timing').getBoundingClientRect();return {row:r.toJSON(),timer:t.toJSON()};},width);
  assert.ok(Math.abs(record.timer.top-record.row.top)<2);assert.ok(record.timer.right<=record.row.right+1);
 }
 await page.evaluate(()=>node.setSize([560,900]));await page.screenshot({path:path.join(out,'speech-running-timer-aligned.png')});
 await page.evaluate(()=>{node.setSize([900,900]);globalThis.mockDelay=400;});
 assert.equal(await page.locator('.hutx-speech-status').count(),1);
 await page.waitForFunction(()=>panel.controller.state.status==='success');
 assert.equal(await page.locator('.hutx-speech-adopt').getAttribute('data-ready'),'true');
 assert.equal(await page.locator('.hutx-speech-actions .hutx-speech-timing:visible').count(),1);
 assert.match(await page.locator('.hutx-speech-timing').textContent(),/完成/);
 assert.equal((await page.locator('.hutx-speech-status').textContent()).includes('完成'),false);
 const timingAligned=await page.evaluate(()=>{const t=document.querySelector('.hutx-speech-timing').getBoundingClientRect(),b=document.querySelector('.hutx-speech-adopt').getBoundingClientRect();return Math.abs((t.top+t.bottom)-(b.top+b.bottom))<3&&t.left>b.right;});assert.equal(timingAligned,true);
 await page.screenshot({path:path.join(out,'speech-ready-to-adopt.png')});
 assert.equal(await page.locator('.hutx-speech-result-heading .hutx-speech-help').count(),1);
 assert.equal((await page.locator('.hutx-speech-status').innerText()).includes('试听'),false);
 await page.getByRole('button',{name:'生成结果与采用说明',exact:true}).hover();
 assert.match(await page.getByRole('tooltip').textContent(),/试听/);
 assert.equal(await page.evaluate(()=>requests.filter(x=>x.path.endsWith('/generate')).length),1);
 const payload=await page.evaluate(()=>requests.find(x=>x.path.endsWith('/generate')).data);
 assert.notEqual(payload.parameters.text,payload.parameters.reference_text);assert.equal(payload.parameters.engine,'cloud');
 await page.getByRole('button',{name:'采用此音频'}).click();await page.waitForFunction(()=>panel.controller.state.adopted);
 assert.equal(await page.locator('.hutx-speech-adopt').getAttribute('data-adopted'),'true');
 assert.equal(await page.locator('.hutx-speech-adopt').getAttribute('data-ready'),'false');
 assert.equal(await page.locator('.hutx-speech-adopt').textContent(),'✓ 已采用');
 assert(await page.locator('.hutx-speech-adopt').isDisabled());
 assert.equal((await page.locator('.hutx-speech-status').textContent()).includes('快照'),false);
 await page.getByRole('button',{name:'生成结果与采用说明',exact:true}).hover();
 assert.match(await page.getByRole('tooltip').textContent(),/快照/);
 assert((await page.evaluate(()=>node.widgets.find(w=>w.name==='adopted_audio_file').value)).endsWith('.json'));
 assert(await page.locator('.hutx-speech-result-audio').isVisible());
 await page.waitForFunction(()=>panel.player.readyState>=1);assert.equal(await page.evaluate(()=>panel.player.duration),1);
 await page.screenshot({path:path.join(out,'speech-success-clone.png')});
 await page.evaluate(()=>panel.hydrate());
 assert.match(await page.evaluate(()=>panel.controller.state.message),/工作流保留了已采用音频/);
 assert((await page.evaluate(()=>node.widgets.find(w=>w.name==='adopted_audio_file').value)).endsWith('.json'));
 await field('text').fill('修改后的新台词');assert(await page.getByRole('button',{name:'采用此音频'}).isDisabled());assert(await page.locator('.hutx-speech-result-audio').isHidden());
 assert.equal(await page.locator('.hutx-speech-adopt').getAttribute('data-adopted'),'false');
 await page.getByRole('button',{name:'生成测试音',exact:true}).click();await page.getByRole('button',{name:'取消',exact:true}).click();
 await page.waitForFunction(()=>!panel.controller.busy);assert.equal(await page.evaluate(()=>panel.controller.state.status),'cancelled');
 assert.equal(await page.locator('.hutx-speech-status').textContent(),'');
 assert.match(await page.locator('.hutx-speech-timing').textContent(),/已取消/);
 await page.screenshot({path:path.join(out,'speech-cancelled.png')});
 await page.evaluate(()=>behavior='error');await page.getByRole('button',{name:'生成测试音',exact:true}).click();
 await page.waitForFunction(()=>panel.controller.state.status==='error');assert(await page.getByRole('button',{name:'生成测试音',exact:true}).isEnabled());
 await page.screenshot({path:path.join(out,'speech-error.png')});
 await page.evaluate(()=>behavior='success');await page.getByRole('button',{name:'生成测试音',exact:true}).click();await field('text').fill('运行中修改');
 await page.waitForFunction(()=>!panel.controller.busy);assert.equal(await page.evaluate(()=>panel.controller.state.result),null);
 await page.evaluate(()=>panel.controller.executed({audio_id:'old-queued-result'}));
 assert.equal(await page.evaluate(()=>panel.controller.state.result),null);
 const serialization=await page.evaluate(()=>JSON.stringify(node.widgets.map(w=>w.value)));
 assert(!serialization.includes('api_key'));assert(!serialization.includes('audio_id'));assert(!serialization.includes('credential_ref'));
 const before=await page.evaluate(()=>requests.length);await page.getByText('视频接入能力（Local AUDIO 桥接）').click();assert.equal(await page.evaluate(()=>requests.length),before);
 await field('mode').selectOption('preset');await field('mock_demo').evaluate(e=>{e.checked=false;e.dispatchEvent(new Event('input',{bubbles:true}));});
 assert(await page.getByRole('button',{name:'生成口播',exact:true}).isDisabled());
 await page.getByText('百炼语音 API 凭证（独立于提示词优化器）').click();
 await page.getByRole('button',{name:'仅本次会话',exact:true}).click();assert(await page.getByText('✕ 请先输入 API Key').isVisible());
 await page.locator('input[type=password]').fill('TEST_UI_SAVE_ONLY');await page.getByRole('button',{name:'仅本次会话',exact:true}).click();
 await page.waitForFunction(()=>credentialState.configured&&!panel.generate.disabled);
 assert.equal(await page.locator('input[type=password]').inputValue(),'');
 assert(await page.locator('[data-field=cloud_model] option[value="cosyvoice-v3.5-plus"]').evaluate(el=>el.disabled),await page.locator('[data-field=cloud_model]').evaluate(el=>el.outerHTML));
 assert.equal(await field('voice').inputValue(),'cloud:longanyang');
 await page.getByRole('button',{name:'生成口播',exact:true}).click();await page.waitForFunction(()=>panel.controller.state.status==='success');
 assert.equal(await page.evaluate(()=>panel.controller.state.result.report.is_mock),false);
 const secretRequests=await page.evaluate(()=>requests.filter(r=>JSON.stringify(r).includes('TEST_UI_SAVE_ONLY')));
 assert.equal(secretRequests.length,1);assert(secretRequests[0].path.endsWith('/credential'));
 assert(!(await page.evaluate(()=>JSON.stringify(node.widgets.map(w=>w.value)))).includes('TEST_UI_SAVE_ONLY'));
 await page.screenshot({path:path.join(out,'speech-cloud-credential.png')});
 for(const [code,text] of [['rate_limit','语音服务限流'],['invalid_credential','语音 API Key 无效'],['oss_cleanup','临时录音清理失败'],['reference_speech','未检测到足够的连续人声'],['queue_busy','队列正在运行']]){
  await page.evaluate(c=>{behavior='error';errorCode=c;},code);
  await page.getByRole('button',{name:'生成口播',exact:true}).click();
  await page.waitForFunction(()=>panel.controller.state.status==='error'&&!panel.controller.busy);
  assert((await page.locator('.hutx-speech-status').innerText()).includes(text));
  assert(!(await page.locator('.hutx-speech-status').innerText()).includes('TEST_PROVIDER_SECRET'));
 }
 await page.screenshot({path:path.join(out,'speech-error-detail.png')});
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'layout.json'),JSON.stringify({widths:records,errors,checks:'four selectors, single timer, success/error/cancel, duplicate, stale, serialize'},null,2));
 console.log(JSON.stringify({status:'PASS',widths:records,screenshots:out}));
} finally {await browser.close();}
