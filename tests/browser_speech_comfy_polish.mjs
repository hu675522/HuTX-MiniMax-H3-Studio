// Actual isolated ComfyUI DOM widgets; all generation and external traffic blocked.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.HUTX_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),out=path.join(root,'.test-artifacts/speech-polish');fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1400,height:1150}});
 await page.route('**/*',route=>{const u=new URL(route.request().url());return u.hostname!=='127.0.0.1'||u.pathname.endsWith('/prompt')||u.pathname.endsWith('/generate')?route.abort():route.continue();});
 await page.goto('http://127.0.0.1:8190',{waitUntil:'networkidle'});
 await page.waitForFunction(()=>window.app?.graph);
 await page.evaluate(async()=>{
  await app.loadGraphData({last_node_id:1,last_link_id:0,nodes:[{id:1,type:'GHSpeechInputGH',pos:[30,70],size:[560,950],flags:{},order:0,mode:0,properties:{}}],links:[],groups:[],config:{},extra:{},version:0.4});
  app.canvas.ds.scale=1;app.canvas.ds.offset=[80,0];app.canvas.setDirty(true,true);
 });
 await page.waitForSelector('.hutx-speech-root');
 assert.equal(await page.locator('[data-field=mode]').inputValue(),'clone');
 assert.equal(await page.locator('.hutx-speech-reference strong').count(),0);
 await page.locator('[data-field=mode]').selectOption('preset');
 await page.waitForFunction(()=>document.querySelector('[data-field=voice] option[value="local:official-b"]'));
 assert.equal(await page.locator('[data-field=voice] option[value^="local:official-"]').count(),2);
 await page.locator('[data-field=voice]').selectOption('local:official-b');
 assert.equal(await page.evaluate(()=>app.graph._nodes[0].widgets.find(w=>w.name==='voice').value),'local:official-b');
 await page.screenshot({path:path.join(out,'speech-builtin-presets.png')});
 await page.locator('[data-field=mode]').selectOption('clone');
 assert(await page.locator('[data-field=reference_file]').isHidden());
 assert(await page.locator('[data-field=reference_text]').isHidden());
 await page.locator('.hutx-speech-root input[type=file]').setInputFiles(path.join(root,'.test-artifacts/speech-stage34/official-reference-pcm16.wav'));
 await page.waitForFunction(()=>document.querySelector('.hutx-speech-reference audio').readyState>=1);
 const referencePath=await page.evaluate(()=>app.graph._nodes[0].widgets.find(w=>w.name==='reference_file').value);
 await page.getByRole('textbox',{name:'参考音频名称',exact:true}).fill('我的参考声线');
 await page.getByRole('textbox',{name:'参考音频名称',exact:true}).press('Tab');
 assert.equal(await page.evaluate(()=>app.graph._nodes[0].widgets.find(w=>w.name==='reference_file').value),referencePath);
 const records=[];
 for(const width of [380,460,560,720,900]){
  await page.evaluate(width=>{app.graph._nodes[0].setSize([width,950]);app.canvas.setDirty(true,true);},width);
  await page.waitForFunction(width=>Math.abs(document.querySelector('.hutx-speech-root').getBoundingClientRect().width-(width-20))<2,width);
  const record=await page.evaluate(()=>{
   const node=app.graph._nodes[0],r=document.querySelector('.hutx-speech-root');
   return {node:node.size[0],root:r.getBoundingClientRect().width,overflow:r.scrollWidth>r.clientWidth+1,
    exposed:node.widgets.filter(w=>w.name!=='speech_panel').filter(w=>!w.hidden||[w.element,w.inputEl].some(e=>e&&getComputedStyle(e).display!=='none'&&e.getBoundingClientRect().height>0)).map(w=>w.name),
    fields:[...r.querySelectorAll('label')].filter(e=>!e.hidden&&e.getBoundingClientRect().height>0&&e.checkVisibility()).map(e=>e.getBoundingClientRect().left)};
  });
  assert.deepEqual(record.exposed,[]);assert.equal(record.overflow,false);assert(record.fields.every(x=>Math.abs(x-record.fields[0])<1));records.push(record);
  await page.screenshot({path:path.join(out,`speech-${width}.png`)});
 }
 await page.evaluate(()=>{const root=document.querySelector('.hutx-speech-root');root.querySelector('.hutx-speech-target')?.closest('details').setAttribute('open','');root.scrollTop=root.scrollHeight;});
 await page.screenshot({path:path.join(out,'speech-capabilities.png')});
 await page.evaluate(()=>{document.querySelector('.hutx-speech-root').scrollTop=0;});
 await page.locator('[data-field=mode]').selectOption('clone');
 await page.screenshot({path:path.join(out,'speech-clone.png')});
 await page.locator('[data-field=engine]').selectOption('cloud');
 await page.screenshot({path:path.join(out,'speech-cloud.png')});
 const saved=await page.evaluate(()=>app.graph.serialize());
 await page.reload({waitUntil:'networkidle'});await page.evaluate(async saved=>{await app.loadGraphData(saved);},saved);
 await page.waitForFunction(()=>document.querySelector('[data-field=engine]')?.value==='cloud');
 assert.equal(await page.getByRole('textbox',{name:'参考音频名称',exact:true}).inputValue(),'我的参考声线');
 await page.getByRole('button',{name:'移除音频',exact:true}).click();
 assert(await page.locator('.hutx-speech-reference audio').isHidden());
 assert.equal(await page.evaluate(()=>app.graph._nodes[0].widgets.find(w=>w.name==='reference_file').value),'');
 fs.writeFileSync(path.join(out,'layout.json'),JSON.stringify({records,reload:true},null,2));console.log(JSON.stringify({records,reload:true}));
}finally{await browser.close();}
