// Visual QA of the real Cloud panel in headless Edge. All requests are mocked.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.HUTX_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, '$1')), '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const browser = await chromium.launch({channel:'msedge',headless:true});
try {
    const page = await browser.newPage({viewport:{width:900,height:920}});
    await page.route('**/*', route => route.abort());
    const errors=[]; page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<html lang="zh"><body style="margin:24px;background:#0c141d"></body></html>');
    const source = read('web/js/studio_theme.js').replace(/\bexport /g,'') + '\n' + read('web/js/video_input_components.js').replace(/\bexport /g,'') + '\n' + read('web/js/responsive_dom_host.js').replace(/\bexport /g,'') + '\n' + read('web/js/gh_video_input_shared.js').replace(/\bexport /g,'') + '\n'
        + read('web/js/prompt_optimizer_shared.js').replace(/\bexport /g,'') + '\n'
        + read('web/js/gh_cloud_video_input.js').replace(/^import[\s\S]*?from\s+["'][^"']+["'];\s*/gm,'');
    await page.addScriptTag({content:`
let extension;
const app={graph:{},extensionManager:{setting:{get:()=> 'zh'}},registerExtension:ext=>{extension=ext;},queuePrompt:async()=>{}};
const api={fetchApi:async(url)=>{
 if(url.endsWith('/config')) return {ok:true,text:async()=>JSON.stringify({mode:'api',provider:'dashscope',environment_api_key_providers:['dashscope'],read_media:false})};
 if(url.endsWith('/optimize')) return await new Promise(resolve=>{globalThis.finishOptimization=()=>resolve({ok:true,text:async()=>JSON.stringify({prompt:'Use <Picture 1> and <Picture 2>, following <Video 1> and <Audio 1>.',report:'{"status":"optimized","optimizer_elapsed_seconds":1.1}'})});});
 throw new Error('Unexpected mock API request');
}};
` + source + `
class Node {
 constructor(){
  this.graph=app.graph; this.mode=0; this.size=[460,760];
  this.properties={gh_cloud_video_state:JSON.stringify({mode:'all_reference',prompt:'Use <Picture 1> and <Picture 2>, following <Video 1> and <Audio 1>.',media:[
   ['ref_image_2',{name:'01.png'}],['ref_image_8',{name:'这是一个很长的中文素材文件名 用于验证省略号与 tooltip (1).png'}],
   ['ref_video_3',{name:'M01_SlowDollyIn_raw.mp4'}],['ref_audio_2',{name:'夏日慢时光.MP3'}]]})};
  this.widgets=['main_mode','prompt','aspect','duration_seconds',...GH_CLOUD_MEDIA_SLOTS,'gh_cloud_state_json','optimizer_enabled','optimized_prompt','optimizer_report'].map(name=>({name,value:''}));
  this.onNodeCreated();
 }
 addDOMWidget(name,type,root){root.style.height='810px';const container=document.createElement('div');container.style.width='438px';container.append(root);document.body.append(container);globalThis.qaContainer=container;return {options:{}};}
 setSize(){} setDirtyCanvas(){}
}
extension.beforeRegisterNodeDef(Node,{name:'GHCloudVideoInputGH'}); globalThis.qaNode=new Node();
`});
    await page.waitForFunction(()=>document.querySelector('.gh-cloud-prompt')?.value.includes('Picture 1'));
    await page.locator('.gh-cloud-prompt').fill('Use @');
    await page.locator('.gh-cloud-picker').waitFor({state:'visible'});
    if(await page.locator('.gh-cloud-picker-row').count() !== 4) throw new Error('Expected four active media');
    const out=path.join(root,'.test-artifacts'); fs.mkdirSync(out,{recursive:true});
    await page.screenshot({path:path.join(out,'prompt-picker.png')});
    await page.locator('.gh-cloud-prompt').press('ArrowDown');
    await page.locator('.gh-cloud-prompt').press('Enter');
    if(await page.locator('.gh-cloud-prompt').inputValue() !== 'Use <Picture 2>') throw new Error('Picker mapping failed');
    const prompt = page.locator('.gh-cloud-prompt');
    const layoutResults = [];
    await page.evaluate(()=>{
        const textarea=document.querySelector('.gh-cloud-prompt');
        const panel=document.querySelector('.gh-cloud-video-root');
        Object.assign(textarea.style,{height:'320px',font:'16px/24px monospace',padding:'8px'});
        panel.style.height=`${textarea.getBoundingClientRect().bottom-panel.getBoundingClientRect().top+28}px`;
        panel.scrollTop=0;
    });
    for (const [name,line,prefix] of [['top',0,'Use '],['middle',5,'Use '],['bottom',11,'x'.repeat(38)]]) {
        await prompt.fill(Array.from({length:line},(_,i)=>`Line ${i}\n`).join('')+prefix+'@');
        await page.locator('.gh-cloud-picker').waitFor({state:'visible'});
        const result=await page.evaluate(({line,prefix})=>{
            const textarea=document.querySelector('.gh-cloud-prompt');
            const node=document.querySelector('.gh-cloud-video-root').getBoundingClientRect();
            const menu=document.querySelector('.gh-cloud-picker').getBoundingClientRect();
            const rect=textarea.getBoundingClientRect(), style=getComputedStyle(textarea);
            const caret=getTextareaCaretRect(textarea,textarea.value.lastIndexOf('@'));
            const canvas=document.createElement('canvas').getContext('2d'); canvas.font=style.font;
            return {node:node.toJSON(),menu:menu.toJSON(),caret,
                expectedTop:rect.top+parseFloat(style.borderTopWidth)+8+line*24,
                expectedLeft:rect.left+parseFloat(style.borderLeftWidth)+8+canvas.measureText(prefix).width};
        },{line,prefix});
        assert.ok(Math.abs(result.caret.top-result.expectedTop)<2,`${name}: caret line ${JSON.stringify(result)}`);
        assert.ok(Math.abs(result.caret.left-result.expectedLeft)<2,`${name}: caret column`);
        assert.ok(result.menu.left>=result.node.left-1 && result.menu.right<=result.node.right+1,`${name}: horizontal node bounds`);
        assert.ok(result.menu.top>=result.node.top-1 && result.menu.bottom<=result.node.bottom+1,`${name}: vertical node bounds`);
        if(name==='bottom') assert.ok(Math.abs(result.menu.bottom-(result.caret.top-3))<2,'Bottom flips above caret');
        else assert.ok(Math.abs(result.menu.top-(result.caret.bottom+3))<2,`${name}: below caret`);
        assert.ok(Math.abs(result.menu.left-Math.max(result.node.left,Math.min(result.caret.left,result.node.right-result.menu.width)))<2,`${name}: caret anchor/clamp`);
        layoutResults.push({name,...result});
        await page.screenshot({path:path.join(out,`prompt-picker-caret-${name}.png`)});
    }
    // Native scrolling and canvas-style transforms must preserve caret coordinates.
    await prompt.fill(Array.from({length:29},()=> 'Scrolled line\n').join('')+'Use @');
    const scrolled=await page.evaluate(()=>{
        const textarea=document.querySelector('.gh-cloud-prompt');
        textarea.scrollTop=textarea.scrollHeight-textarea.clientHeight;
        textarea.dispatchEvent(new Event('scroll'));
        const a=getTextareaCaretRect(textarea,textarea.value.lastIndexOf('@'));
        const root=document.querySelector('.gh-cloud-video-root');
        const origin=root.getBoundingClientRect();
        root.style.transformOrigin='top left';root.style.transform='scale(0.75)';
        window.dispatchEvent(new Event('resize'));
        const b=getTextareaCaretRect(textarea,textarea.value.lastIndexOf('@'));
        const menu=document.querySelector('.gh-cloud-picker').getBoundingClientRect();
        return {a,b,origin:origin.toJSON(),menu:menu.toJSON(),hidden:document.querySelector('.gh-cloud-picker').hidden};
    });
    assert.equal(scrolled.hidden,false);
    assert.ok(Math.abs(scrolled.b.top-(scrolled.origin.top+(scrolled.a.top-scrolled.origin.top)*0.75))<2,'Zoom scales vertical caret');
    assert.ok(Math.abs(scrolled.b.left-(scrolled.origin.left+(scrolled.a.left-scrolled.origin.left)*0.75))<2,'Zoom scales horizontal caret');
    assert.ok(Math.abs(scrolled.menu.bottom-(scrolled.b.top-3))<2,'Scrolled caret popup stays nearby');
    await page.evaluate(()=>{
        const root=document.querySelector('.gh-cloud-video-root');root.style.transform='';root.style.height='810px';root.scrollTop=0;
        const textarea=document.querySelector('.gh-cloud-prompt');textarea.style.height='118px';
    });
    for(const prefix of ['abc','中文','<Video 1>','<Picture 1>','<Audio 1>','，','。']) {
        await prompt.fill(prefix);
        await prompt.press('End');await page.keyboard.insertText('@');
        assert.equal(await page.locator('.gh-cloud-picker').isVisible(),true,`${prefix}@ opens picker`);
    }
    await prompt.fill('@'); await prompt.press('Enter');
    await page.keyboard.insertText('@');
    assert.equal(await page.locator('.gh-cloud-picker').isVisible(),true,'Second adjacent @ opens');
    // An IME query must not dismiss the active mention during composition.
    await prompt.dispatchEvent('compositionstart');
    await page.keyboard.insertText('视');
    await prompt.dispatchEvent('compositionend');
    assert.equal(await page.locator('.gh-cloud-picker-row').count(),1);
    await prompt.press('Enter');
    assert.equal(await prompt.inputValue(),'<Picture 1><Video 1>');
    assert.equal(await prompt.evaluate(el=>el.selectionStart),'<Picture 1><Video 1>'.length);
    assert.equal(await page.locator('.gh-opt-status').count(),0);
    await page.locator('.gh-opt-run').click();
    await page.waitForFunction(()=>!!globalThis.finishOptimization);
    await page.waitForTimeout(450);
    assert.equal(await page.locator('.gh-opt-timing:visible').count(),1);
    await page.screenshot({path:path.join(out,'prompt-timer-running.png')});
    await page.evaluate(()=>globalThis.finishOptimization());
    await page.waitForFunction(()=>document.querySelector('.gh-opt-timing').dataset.state === 'success');
    assert.equal(await page.locator('.gh-opt-timing:visible').count(),1);
    await page.screenshot({path:path.join(out,'prompt-timer-success.png')});
    await page.locator('.gh-prompt-tabs button').filter({hasText:'对比'}).click();
    assert.equal(await page.locator('.gh-prompt-readonly textarea').count(),2);
    assert.equal(await page.locator('.gh-prompt-readonly textarea').first().inputValue(),'<Picture 1><Video 1>');
    const optimized=await page.locator('.gh-prompt-readonly textarea').last().inputValue();
    await page.screenshot({path:path.join(out,'prompt-before-after.png')});
    await page.locator('.gh-prompt-restore').click();
    assert.equal(await prompt.inputValue(),'<Picture 1><Video 1>');
    await page.locator('.gh-prompt-apply').click();
    assert.equal(await prompt.inputValue(),optimized);
    const responsive=[];
    await page.setViewportSize({width:1100,height:1100});
    await prompt.fill('x'.repeat(34)+'@');
    for(const width of [380,460,560,720,900]) {
        await page.evaluate(width=>{globalThis.qaContainer.style.width=width+'px';},width);
        await page.waitForFunction(width=>Math.abs(document.querySelector('.gh-cloud-video-root').getBoundingClientRect().width-width)<1,width);
        // ResizeObserver must move the already-open popup, without another input event.
        await page.waitForFunction(()=>{
            const node=document.querySelector('.gh-cloud-video-root').getBoundingClientRect();
            const menu=document.querySelector('.gh-cloud-picker').getBoundingClientRect();
            return menu.left>=node.left-1 && menu.right<=node.right+1;
        });
        const layout=await page.evaluate(()=>{
            const root=document.querySelector('.gh-cloud-video-root');
            const textarea=document.querySelector('.gh-cloud-prompt');
            const node=root.getBoundingClientRect(), prompt=textarea.getBoundingClientRect();
            const menu=document.querySelector('.gh-cloud-picker').getBoundingClientRect();
            const caret=getTextareaCaretRect(textarea,textarea.value.lastIndexOf('@'));
            const style=getComputedStyle(root);
            const contentWidth=root.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
            return {width:node.width,prompt:prompt.width,available:contentWidth,
                overflow:root.scrollWidth>root.clientWidth,menu:menu.toJSON(),caret,node:node.toJSON(),
                groups:[...root.querySelectorAll('.gh-cloud-section')].map(el=>el.getBoundingClientRect().width)};
        });
        assert.ok(Math.abs(layout.prompt-layout.available)<2,`${width}: prompt fills available width`);
        assert.ok(layout.groups.every(w=>Math.abs(w-layout.available)<2),`${width}: media sections stretch`);
        assert.equal(layout.overflow,false,`${width}: no overflow`);
        assert.ok(Math.min(Math.abs(layout.menu.top-layout.caret.bottom-3),Math.abs(layout.menu.bottom-layout.caret.top+3))<2,`${width}: resized caret anchor`);
        responsive.push(layout);
        await page.screenshot({path:path.join(out,`cloud-width-${width}.png`)});
    }
    await prompt.press('Escape');
    await page.locator('.gh-ratio-trigger').click();
    assert.equal(await page.locator('.gh-ratio-item').count(),7);
    await page.screenshot({path:path.join(out,'cloud-ratio-grid.png')});
    for(const value of ['adaptive','21:9','16:9','4:3','1:1','3:4','9:16']) {
        if(!await page.locator('.gh-ratio-popup').isVisible())await page.locator('.gh-ratio-trigger').click();
        await page.locator(`.gh-ratio-item[value="${value}"]`).click();
        assert.equal(await page.evaluate(()=>qaNode.widgets.find(w=>w.name==='aspect').value),value);
    }
    await page.addScriptTag({content:read('web/js/fal_credentials.js').replace(/^import .*;$/gm,'').replace(/\bexport /g,'')});
    await page.evaluate(()=>{
        globalThis.falRequests=[];
        let configured=false,source='missing';
        const mocked={fetchApi:async(url,options)=>{
            const body=options.body?JSON.parse(await options.body.text()):undefined;
            falRequests.push({url,method:options.method,body});
            if(options.method==='POST'){configured=true;source=body.storage;}
            if(options.method==='DELETE'){configured=false;source='missing';}
            return {ok:true,json:async()=>({configured,active_source:configured?source:'none',environment_configured:false,session_configured:source==='session',persisted_configured:source==='persisted',persistence_supported:true})};
        }};
        const panel=createFalCredentialPanel(mocked);
        const host=document.createElement('div');host.style.width='380px';host.append(panel.element);document.body.prepend(host);
        panel.element.open=true;panel.refresh();
    });
    await page.locator('.hutx-fal-key').fill('TEST_FAL_KEY');
    await page.locator('.hutx-fal-save').click();
    await page.waitForFunction(()=>document.querySelector('.hutx-fal-active').textContent==='当前生效： ● 本机安全存储');
    assert.equal(await page.locator('.hutx-fal-key').inputValue(),'');
    assert.ok(!(await page.locator('body').innerText()).includes('TEST_FAL_KEY'));
    const falRequests=await page.evaluate(()=>falRequests);
    assert.equal(falRequests.filter(r=>JSON.stringify(r).includes('TEST_FAL_KEY')).length,1);
    assert.equal(falRequests.find(r=>r.method==='POST').body.key,'TEST_FAL_KEY');
    await page.screenshot({path:path.join(out,'fal-credential-configured.png')});
    const overflow=await page.evaluate(()=>({page:document.body.scrollWidth>innerWidth,panel:document.querySelector('.gh-cloud-video-root').scrollWidth>document.querySelector('.gh-cloud-video-root').clientWidth}));
    if(errors.length || overflow.page || overflow.panel) throw new Error(JSON.stringify({errors,overflow}));
    fs.writeFileSync(path.join(out,'prompt-picker-layout.json'),JSON.stringify({layoutResults,scrolled,responsive},null,2));
    console.log(JSON.stringify({screenshots:14,layoutCases:layoutResults.map(item=>item.name),responsiveWidths:responsive.map(r=>r.width),ratioRoundTrip:true,promptHistory:true,falCredentialUI:true,scrollAndZoom:true,continuousMentions:true,errors,overflow,output:out}));
} finally { await browser.close(); }
