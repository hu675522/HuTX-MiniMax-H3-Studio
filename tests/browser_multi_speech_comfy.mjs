// Actual ComfyUI node/DOM and Python mock speech only. Never queue models.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.HUTX_PLAYWRIGHT_MODULE||'playwright');
const out=path.resolve('.test-artifacts/multi-speech');fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1800,height:1250}}),errors=[],calls=[];
 page.on('pageerror',e=>errors.push(e.message));
 let active=0,peak=0;
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url());
  if(u.hostname!=='127.0.0.1'||u.pathname.endsWith('/prompt')||u.pathname.endsWith('/optimize'))return route.abort();
  if(u.pathname.endsWith('/api/hutx/minimax-h3/local-media-info'))return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({width:960,height:544,has_audio:true})});
  if(u.pathname.endsWith('/generate')){
   const data=req.postDataJSON();assert.equal(data.parameters.mock_demo,true);calls.push(data);active++;peak=Math.max(peak,active);
   try{await new Promise(r=>setTimeout(r,250));const response=await route.fetch();await route.fulfill({response});}finally{active--;}
   return;
  }return route.continue();
 });
 await page.goto('http://127.0.0.1:8190',{waitUntil:'networkidle'});
 await page.waitForFunction(()=>window.app?.graph);
 await page.evaluate(async()=>{
  const state={schema_version:1,mode:'all_reference',prompt:'<Picture 1>',media:[['ref_image_1',{name:'person.png',kind:'image'}],['ref_video_1',{name:'clip.mp4',kind:'video'}],['first_frame',{name:'person.png',kind:'image'}]]};
  await app.loadGraphData({last_node_id:2,last_link_id:0,nodes:[
   {id:1,type:'GHMultiSpeechInputGH',pos:[20,60],size:[530,1060],flags:{},order:0,mode:0,properties:{}},
   {id:2,type:'GHLocalVideoInputGH',pos:[650,60],size:[660,1120],flags:{},order:1,mode:0,properties:{gh_local_video_state:JSON.stringify(state)}}
  ],links:[],groups:[],config:{},extra:{},version:0.4});
  app.canvas.ds.scale=1;app.canvas.ds.offset=[50,0];app.canvas.setDirty(true,true);
 });
 await page.waitForSelector('.hutx-multi-speech');
 const role=letter=>page.locator(`.hutx-role[data-role=${letter}]`);
 assert.equal(await page.locator('.hutx-role[open]').count(),3);
 assert.equal(await page.locator('.hutx-multi-shared [data-field=engine]').count(),1);
 assert(await page.locator('.hutx-multi-shared .hutx-speech-debug').isHidden());
 assert.equal(await page.locator('.hutx-multi-speech > strong').count(),0);
 assert(await page.locator('.hutx-multi-instructions').evaluate(e=>e.nextElementSibling.classList.contains('hutx-multi-shared')));
 await page.locator('.hutx-multi-shared [data-field=mock_demo]').evaluate(e=>{e.checked=true;e.dispatchEvent(new Event('input',{bubbles:true}));});
 for(const letter of 'ABC'){
  await role(letter).locator('[data-field=mode]').selectOption('preset');
  await role(letter).locator('[data-field=voice]').selectOption('local:demo-a');
  await role(letter).locator('[data-field=text]').fill(`角色${letter}的台词。`);
  await role(letter).getByRole('textbox',{name:`角色 ${letter} 名称`}).fill('同名角色');
 }
 await page.getByRole('button',{name:'生成待更新角色',exact:true}).click();
 await page.waitForFunction(()=>[...document.querySelectorAll('.hutx-role-state')].every(e=>e.textContent==='待采用'));
 assert.equal(calls.length,3);assert.equal(peak,1);
 await page.getByRole('button',{name:'采用全部已生成结果',exact:true}).click();
 await page.waitForFunction(()=>[...document.querySelectorAll('.hutx-role-state')].every(e=>e.textContent==='✓ 已采用'));
 const adopted=()=>page.evaluate(()=>app.graph.getNodeById(1).widgets.filter(w=>/^role_/.test(w.name)).map(w=>JSON.parse(w.value).adopted_audio_file));
 const original=await adopted();assert.equal(new Set(original).size,3);
 // A single adopted speech cable may remain connected at the same time. The
 // current Local mode, rather than cable presence, selects the active family.
 await page.evaluate(ref=>{
  const single=LiteGraph.createNode('GHSpeechInputGH');single.id=3;single.pos=[590,1190];app.graph.add(single);
  const set=(name,value)=>{const w=single.widgets.find(item=>item.name===name);if(w)w.value=value;};
  set('mode','preset');set('text','单人口播');set('voice','local:demo-a');set('mock_demo',true);set('adopted_audio_file',ref);
  const local=app.graph.getNodeById(2);single.connect(0,local,local.inputs.findIndex(e=>e.name==='driver_audio'));
 },original[0]);
 const audioPlayer=role('A').locator('.hutx-speech-result .hutx-audio-player');
 assert(await audioPlayer.isVisible());
 await audioPlayer.getByRole('button',{name:'播放音频',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('[data-role=A] .hutx-speech-result audio').paused);
 await audioPlayer.getByRole('button',{name:'暂停音频',exact:true}).click();
 const canSeek=await role('A').locator('.hutx-speech-result audio').evaluate(e=>!!e.seekable.length&&e.seekable.end(e.seekable.length-1)>0);
 assert.equal(await audioPlayer.getByRole('slider',{name:'音频进度'}).isDisabled(),!canSeek);
 if(canSeek){await audioPlayer.getByRole('slider',{name:'音频进度'}).evaluate(e=>{e.value=500;e.dispatchEvent(new Event('input'));});
  await page.waitForFunction(()=>{const a=document.querySelector('[data-role=A] .hutx-speech-result audio');return Math.abs(a.currentTime-a.duration/2)<.1;});}
 await audioPlayer.getByRole('button',{name:'静音',exact:true}).click();
 assert(await role('A').locator('.hutx-speech-result audio').evaluate(e=>e.muted));
 await audioPlayer.getByRole('button',{name:'取消静音',exact:true}).click();
 await page.evaluate(()=>{
  const source=app.graph.getNodeById(1),target=app.graph.getNodeById(2);
  for(let i=0;i<3;i++)source.connect(i,target,target.inputs.findIndex(e=>e.name===`reference_audio_${i+1}`));
 });
 await page.waitForFunction(()=>document.querySelectorAll('.gh-local-media [data-connected-audio=true]').length===3);
 const labels=await page.locator('.gh-local-media [data-connected-audio=true]').evaluateAll(cards=>cards.map(c=>({slot:c.dataset.slot,text:c.textContent})));
 assert.deepEqual(labels.map(x=>x.slot),['ref_audio_1','ref_audio_2','ref_audio_3']);
 for(let i=0;i<3;i++)assert(labels[i].text.includes(`<Audio ${i+1}>`));
 assert((await page.locator('.gh-local-role-status').textContent()).includes('自动忽略参考视频原声'));
 await page.locator('.gh-local-video-root .gh-cloud-modes button[value=text_keyframes]').click();
 await page.evaluate(()=>document.querySelector('.gh-local-driver').open=true);
 await page.locator('[data-driver=driver_model_family]').selectOption('FL2VA');
 await page.waitForSelector('[data-slot=hybrid_audio][data-connected-audio=true]');
 assert.equal(await page.locator('.gh-local-media [data-connected-audio=true]').count(),1);
 await page.locator('.gh-local-video-root .gh-cloud-modes button[value=all_reference]').click();
 await page.waitForFunction(()=>document.querySelectorAll('.gh-local-media [data-connected-audio=true]').length===3);
 const prompt=page.locator('.gh-local-video-root .gh-cloud-prompt');
 await prompt.fill('<Picture 1>');await prompt.press('End');await prompt.press('@');
 await page.getByRole('option').filter({hasText:'音频2'}).click();
 assert.equal(await prompt.inputValue(),'<Picture 1><Audio 2>');
 const records=[];
 for(const width of [380,460,560,720,900,1160]){
  await page.evaluate(width=>{app.graph.getNodeById(1).setSize([width,1080]);app.canvas.setDirty(true,true);},width);
  await page.waitForFunction(width=>Math.abs(document.querySelector('.hutx-multi-speech').getBoundingClientRect().width-(width-20))<2,width);
  const record=await page.evaluate(()=>{const r=document.querySelector('.hutx-multi-speech'),rect=r.getBoundingClientRect();return {node:app.graph.getNodeById(1).size[0],root:rect.width,overflow:r.scrollWidth>r.clientWidth+1,cards:[...r.querySelectorAll('.hutx-role')].map(e=>({left:e.getBoundingClientRect().left,top:e.getBoundingClientRect().top,width:e.getBoundingClientRect().width}))};});
  assert.equal(record.overflow,false);if(width<1100)assert.equal(new Set(record.cards.map(c=>c.left)).size,1);else assert.equal(new Set(record.cards.map(c=>c.top)).size,1);
  records.push(record);await page.screenshot({path:path.join(out,`cards-${width}.png`)});
 }
 await page.evaluate(()=>{app.graph.getNodeById(1).setSize([530,1080]);app.canvas.setDirty(true,true);});
 await role('B').locator('[data-field=text]').fill('只更新乙角色。');
 const modified=await adopted();assert.equal(modified[0],original[0]);assert.equal(modified[1],'');assert.equal(modified[2],original[2]);
 await page.getByRole('button',{name:'生成待更新角色',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-role=B] .hutx-role-state').textContent==='待采用');assert.equal(calls.length,4);
 await role('B').getByRole('button',{name:'采用此音频',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-role=B] .hutx-role-state').textContent==='✓ 已采用');
 await role('C').getByRole('button',{name:'展开或折叠角色 C'}).click();assert.equal(await role('C').getAttribute('open'),null);
 const graph=await page.evaluate(()=>app.graph.serialize());
 const local=graph.nodes.find(n=>n.id===2);assert(!local.properties.gh_local_video_state.includes('hutx-speech/adopted/'));
 fs.writeFileSync(path.join(out,'mock-workflow.json'),JSON.stringify(graph,null,2));
 await page.reload({waitUntil:'networkidle'});await page.evaluate(async data=>{await app.loadGraphData(data);app.canvas.ds.scale=1;app.canvas.ds.offset=[50,0];app.canvas.setDirty(true,true);},graph);
 await page.waitForFunction(()=>document.querySelectorAll('.gh-local-media [data-connected-audio=true]').length===3);
 assert.equal(await role('C').getAttribute('open'),null);assert.equal(calls.length,4);
 assert.deepEqual((await adopted()).filter(Boolean).length,3);
 // Disabled role removes preview without shifting the other physical slots.
 await role('B').getByRole('checkbox',{name:'启用角色 B'}).uncheck();
 await page.waitForFunction(()=>document.querySelectorAll('.gh-local-media [data-connected-audio=true]').length===2);
 assert.deepEqual(await page.locator('.gh-local-media [data-connected-audio=true]').evaluateAll(x=>x.map(e=>e.dataset.slot)),['ref_audio_1','ref_audio_3']);
 assert.deepEqual(await page.locator('.gh-local-media [data-connected-audio=true]').evaluateAll(x=>x.map(e=>e.textContent.match(/<Audio \d+>/)?.[0])),['<Audio 1>','<Audio 2>']);
 await role('A').getByRole('checkbox',{name:'启用角色 A'}).uncheck();
 await page.waitForFunction(()=>document.querySelectorAll('.gh-local-media [data-connected-audio=true]').length===1);
 assert((await page.locator('.gh-local-media [data-connected-audio=true]').textContent()).includes('<Audio 1>'));
 await role('A').getByRole('checkbox',{name:'启用角色 A'}).check();
 await page.waitForFunction(()=>document.querySelectorAll('.gh-local-media [data-connected-audio=true]').length===2);
 assert.equal(calls.length,4);assert.deepEqual(errors,[]);
 // Reference upload/rename belongs to A alone; the mock exercises clone request shape.
 await role('A').locator('[data-field=mode]').selectOption('clone');
 await role('A').locator('input[type=file]').setInputFiles(path.resolve('assets/speech_voices/a.wav'));
 await page.waitForFunction(()=>document.querySelector('[data-role=A] .hutx-speech-reference audio')?.readyState>=1);
 await role('A').getByRole('textbox',{name:'参考音频名称',exact:true}).fill('角色甲参考录音');
 await role('A').getByRole('textbox',{name:'参考音频名称',exact:true}).press('Tab');
 await role('A').getByRole('button',{name:'生成测试音',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-role=A] .hutx-role-state').textContent==='待采用');
 assert.equal(calls.length,5);assert.equal(calls[4].parameters.mode,'clone');assert(calls[4].reference_file.endsWith('.wav'));
 assert.equal(await role('C').locator('[data-field=mode]').inputValue(),'preset');
 // Shared engine/config changes invalidate all roles, never silently reuse old voices.
 await page.locator('.hutx-multi-shared [data-field=engine]').selectOption('cloud');
 assert.deepEqual(await page.evaluate(()=>app.graph.getNodeById(1).widgets.filter(w=>/^role_/.test(w.name)).map(w=>JSON.parse(w.value).engine)),['cloud','cloud','cloud']);
 assert((await adopted()).every(ref=>!ref));
 assert.equal(await page.locator('.hutx-multi-speech input[type=password]:visible').count(),0); // closed credential details
 assert.equal(await page.locator('.hutx-multi-shared details').filter({hasText:'百炼语音 API 凭证'}).count(),1);
 assert(!JSON.stringify(await page.evaluate(()=>app.graph.serialize())).includes('api_key'));
 fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify({records,labels,calls:calls.length,peakConcurrent:peak,errors},null,2));
 console.log(JSON.stringify({passed:true,calls:calls.length,peakConcurrent:peak,records}));
}finally{await browser.close();}
