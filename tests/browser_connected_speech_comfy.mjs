// Real ComfyUI graph wiring/adoption; only explicit backend mock audio is allowed.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.HUTX_PLAYWRIGHT_MODULE||'playwright');
const out=path.resolve('.test-artifacts/connected-speech');fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
 const page=await browser.newPage({viewport:{width:1600,height:1300}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.hostname!=='127.0.0.1'||url.pathname.endsWith('/prompt')||url.pathname.endsWith('/optimize'))return route.abort();
  if(url.pathname.endsWith('/generate')&&req.postDataJSON()?.parameters?.mock_demo!==true)return route.abort();
  return route.continue();
 });
 await page.goto('http://127.0.0.1:8190',{waitUntil:'networkidle'});
 await page.waitForFunction(()=>window.app?.graph);
 await page.evaluate(async()=>{
  const state={schema_version:1,mode:'text_keyframes',prompt:'<Picture 1>',media:[['first_frame',{name:'person.png',kind:'image'}]]};
  await app.loadGraphData({last_node_id:2,last_link_id:0,nodes:[
   {id:1,type:'GHSpeechInputGH',pos:[30,60],size:[510,1080],flags:{},order:0,mode:0,properties:{}},
   {id:2,type:'GHLocalVideoInputGH',pos:[610,60],size:[650,1120],flags:{},order:1,mode:0,properties:{gh_local_video_state:JSON.stringify(state)}}
  ],links:[],groups:[],config:{},extra:{},version:0.4});
  app.canvas.ds.scale=1;app.canvas.ds.offset=[100,0];app.canvas.setDirty(true,true);
 });
 await page.waitForSelector('.hutx-speech-root');
 assert.equal(await page.locator('[data-field=mock_demo]').isVisible(),false);
 assert(await page.locator('.hutx-speech-debug').isHidden());
 await page.locator('[data-field=mock_demo]').evaluate(e=>{e.checked=true;e.dispatchEvent(new Event('input',{bubbles:true}));});
 await page.locator('[data-field=mode]').selectOption('preset');
 await page.locator('[data-field=voice]').selectOption('local:demo-a');
 await page.locator('[data-field=text]').fill('仅用于接口测试的模拟口播。');
 await page.locator('.hutx-speech-row button').filter({hasText:'生成测试音'}).click();
 await page.getByRole('button',{name:'采用此音频',exact:true}).waitFor();
 await page.waitForFunction(()=>[...document.querySelectorAll('.hutx-speech-row button')].some(b=>b.textContent==='采用此音频'&&!b.disabled));
 await page.getByRole('button',{name:'采用此音频',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.hutx-speech-result-header strong').textContent.includes('已采用'));
 assert.equal(await page.locator('.hutx-speech-result-header a').textContent(),'下载 WAV');
 assert.equal(await page.locator('.hutx-speech-reference p').count(),0);
 await page.waitForFunction(()=>app.graph.getNodeById(1).widgets.find(w=>w.name==='adopted_audio_file').value);
 await page.evaluate(()=>document.querySelector('.gh-local-driver').open=true);
 assert.match(await page.locator('.gh-local-driver-status').textContent(),/尚未连接/);
 await page.locator('[data-driver=driver_model_family]').selectOption('FL2VA');
 await page.locator('[data-driver=driver_slot]').selectOption('hybrid_audio');
 await page.evaluate(()=>{
  const speech=app.graph.getNodeById(1),local=app.graph.getNodeById(2);
  speech.connect(0,local,local.inputs.findIndex(i=>i.name==='driver_audio'));
 });
 await page.waitForSelector('[data-connected-audio=true]');
 await page.waitForFunction(()=>document.querySelector('[data-connected-audio=true] audio')?.readyState>=1);
 assert.deepEqual(await page.locator('[data-driver=driver_slot] option:not([hidden])').evaluateAll(items=>items.map(e=>e.value)),['hybrid_audio']);
 assert.equal(await page.evaluate(()=>document.querySelector('.gh-local-driver').previousElementSibling.classList.contains('gh-cloud-modes')),true);
 const prompt=page.locator('.gh-local-video-root .gh-cloud-prompt');
 await prompt.fill('<Picture 1>');await prompt.press('End');await prompt.press('@');
 await page.getByRole('option').filter({hasText:'已采用口播'}).click();
 assert.equal(await prompt.inputValue(),'<Picture 1><Audio 1>');
 await page.screenshot({path:path.join(out,'connected-audio.png')});
 const saved=await page.evaluate(()=>app.graph.serialize());
 assert.equal(JSON.parse(saved.nodes.find(n=>n.id===2).properties.gh_local_video_state).media.some(([s])=>s==='hybrid_audio'),false);
 await page.reload({waitUntil:'networkidle'});
 await page.evaluate(async saved=>{await app.loadGraphData(saved);app.canvas.ds.scale=1;app.canvas.ds.offset=[100,0];app.canvas.setDirty(true,true);},saved);
 await page.waitForSelector('[data-connected-audio=true]');
 await page.waitForFunction(()=>document.querySelector('[data-connected-audio=true] audio')?.readyState>=1);
 await page.screenshot({path:path.join(out,'reloaded-audio.png')});
 assert.equal(await page.locator('.hutx-speech-adopt').getAttribute('data-adopted'),'true');
 assert.equal(await page.locator('.hutx-speech-adopt').textContent(),'✓ 已采用');
 await page.getByRole('button',{name:'生成结果与采用说明',exact:true}).hover();
 assert.match(await page.getByRole('tooltip').textContent(),/执行时校验/);
 // Tail-only L2VA uses the same hybrid_audio bridge as first-frame I2VA.
 await page.evaluate(()=>{
  const node=app.graph.getNodeById(2),state=JSON.parse(node.properties.gh_local_video_state);
  state.prompt='<Picture 1><Audio 1>';state.media=state.media.filter(([slot])=>!['first_frame','last_frame'].includes(slot));
  state.media.push(['last_frame',{name:'tail.png',kind:'image'}]);
  node.properties.gh_local_video_state=JSON.stringify(state);node.onConfigure({properties:{gh_local_video_state:node.properties.gh_local_video_state}});
 });
 await page.waitForSelector('[data-slot=hybrid_audio][data-connected-audio=true]');
 assert.match(await page.locator('.gh-local-driver-status').textContent(),/已连接采用口播/);
 // Mode changes invalidate incompatible confirmation, but never switch weights.
 const originalModel=await page.locator('[data-config=model_name]').inputValue();
 await page.locator('.gh-local-video-root .gh-cloud-modes button[value=all_reference]').click();
 assert.equal(await page.locator('[data-driver=driver_model_family]').inputValue(),'unconfirmed');
 assert.deepEqual(await page.locator('[data-driver=driver_model_family] option:not([hidden])').evaluateAll(items=>items.map(e=>e.value)),['unconfirmed','Ref2VA']);
 assert.deepEqual(await page.locator('[data-driver=driver_slot] option:not([hidden])').evaluateAll(items=>items.map(e=>e.value)),['ref_audio_1','ref_audio_2','ref_audio_3']);
 assert.equal(await page.locator('[data-config=model_name]').inputValue(),originalModel);
 await page.evaluate(()=>document.querySelector('.gh-local-driver').open=true);
 assert.match(await page.locator('.gh-local-driver-compatibility').textContent(),/切换为 Ref2VA/);
 await page.screenshot({path:path.join(out,'reference-mode-controls.png')});
 await page.locator('[data-driver=driver_model_family]').selectOption('Ref2VA');
 await page.waitForSelector('[data-slot=ref_audio_1][data-connected-audio=true]');
 assert.match(await page.locator('.gh-local-driver-status').textContent(),/添加参考图片或视频/);
 await page.locator('[data-driver=driver_slot]').selectOption('ref_audio_2');
 await page.waitForSelector('[data-slot=ref_audio_2][data-connected-audio=true]');
 await page.waitForFunction(()=>document.querySelector('[data-connected-audio=true] audio')?.readyState>=1);
 await page.screenshot({path:path.join(out,'reference-audio-without-picture.png')});
 await page.locator('.gh-local-video-root .gh-cloud-modes button[value=text_keyframes]').click();
 assert.equal(await page.locator('[data-driver=driver_model_family]').inputValue(),'unconfirmed');
 assert.deepEqual(await page.locator('[data-driver=driver_slot] option:not([hidden])').evaluateAll(items=>items.map(e=>e.value)),['hybrid_audio']);
 await page.locator('[data-driver=driver_model_family]').selectOption('FL2VA');
 await page.waitForSelector('[data-connected-audio=true]');
 await page.evaluate(()=>{const n=app.graph.getNodeById(2);n.disconnectInput(n.inputs.findIndex(i=>i.name==='driver_audio'));});
 await page.waitForFunction(()=>!document.querySelector('[data-connected-audio=true]'));
 assert.match(await page.locator('.gh-local-driver-status').textContent(),/尚未连接/);
 assert.equal(await prompt.inputValue(),'<Picture 1><Audio 1>'); // stale text is not silently rewritten
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'audit.json'),JSON.stringify({mockOnly:true,actualGraphWiring:true,adoptedPreviewPlayable:true,canonicalTag:'<Audio 1>',reload:true,disconnect:true,errors},null,2));
 console.log('Real ComfyUI: adopted mock audio, wiring, playback, @ tag, serialization/reload and disconnect PASS');
}finally{await browser.close();}
