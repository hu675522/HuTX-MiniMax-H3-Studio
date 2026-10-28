// Opt-in real ComfyUI frontend check. POST /prompt, speech and optimizer calls are forbidden.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url), {chromium} = require(process.env.HUTX_PLAYWRIGHT_MODULE || 'playwright');
const out = path.resolve('.test-artifacts/workbench'); fs.mkdirSync(out, {recursive: true});
const browser = await chromium.launch({channel: 'msedge', headless: true});
try {
    const page = await browser.newPage({viewport: {width: 1600, height: 1100}}), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
        const request = route.request(), url = new URL(request.url());
        if (url.hostname !== '127.0.0.1' || (request.method() === 'POST' && /\/prompt$|\/generate$|\/optimize$/.test(url.pathname))) return route.abort();
        return route.continue();
    });
    await page.goto(process.env.HUTX_TEST_COMFY_URL || 'http://127.0.0.1:8190', {waitUntil: 'networkidle'});
    await page.evaluate(async () => {
        const {app} = await import('/scripts/app.js'); globalThis.hostApp = app;
        await app.loadGraphData({nodes: [], links: [], groups: [], config: {}, extra: {}, version: 0.4});
        const manager = app.extensionManager;
        if (!manager.getSidebarTabs().some(tab => tab.id === 'hutx-studio-workbench')) throw Error('Workbench sidebar was not registered');
        if (manager.sidebarTab.activeSidebarTabId !== 'hutx-studio-workbench') manager.sidebarTab.toggleSidebarTab('hutx-studio-workbench');
    });
    // Fresh isolated user directories can open the native template browser.
    await page.keyboard.press('Escape');
    const closeDialog=page.locator('.p-dialog-close-button:visible');
    if(await closeDialog.count())await closeDialog.first().click();
    await page.screenshot({path: path.join(out, 'real-host-initial.png')});
    const workbench = page.locator('.hutx-workbench');
    await workbench.getByRole('button', {name: '添加三角色口播', exact: true}).click();
    await workbench.locator('[data-role=A] [data-field=text]').fill('真实前端参数同步验证。');
    await workbench.locator('[data-role=A] [data-field=text]').dispatchEvent('input');
    await workbench.getByRole('tab', {name: /镜头生成/}).click();
    await workbench.getByRole('button', {name: '添加基础单采线路', exact: true}).click();
    await workbench.getByRole('textbox', {name: 'Local Prompt', exact: true}).fill('A character walks slowly.');
    await workbench.getByRole('textbox', {name: 'Local Prompt', exact: true}).dispatchEvent('input');
    const leaseIdentity=await page.evaluate(()=>{
        const source=hostApp.graph._nodes.find(node=>node.type==='GHLocalVideoInputDualEngineGH'),panel=source.hutxWorkbenchPanel;
        const widget=source.widgets.find(widget=>widget.name==='gh_local_video_panel');
        if(widget.element!==panel.canvasHost||widget.element===panel.element)throw Error('Renderer must own the stable shell only');
        globalThis.nativeCanonicalPanel=panel.element;globalThis.nativeCanvasHostParent=panel.canvasHost.parentNode;
        panel.canvasHost.remove();panel.canvasHost.querySelector('.hutx-workbench-placeholder')?.remove();return source.id;
    });
    await workbench.getByRole('tab',{name:/角色与声音/}).click();
    await workbench.getByRole('tab',{name:/镜头生成/}).click();
    await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).waitFor();
    await workbench.getByRole('button',{name:'定位节点',exact:true}).click();
    await workbench.getByRole('button',{name:'在工作台编辑',exact:true}).click();
    await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).waitFor();
    await page.evaluate(()=>nativeCanonicalPanel.remove());
    await page.waitForFunction(()=>document.querySelector('.hutx-workbench .gh-local-video-root')===nativeCanonicalPanel);
    assert.equal(await workbench.getByRole('textbox',{name:'Local Prompt',exact:true}).inputValue(),'A character walks slowly.');
    await page.evaluate(id=>{const panel=hostApp.graph.getNodeById(id).hutxWorkbenchPanel;if(panel.element!==nativeCanonicalPanel)throw Error('Controller was recreated');nativeCanvasHostParent?.append(panel.canvasHost);},leaseIdentity);
    await workbench.getByRole('button', {name: '将当前设置保存为镜头', exact: true}).click();
    await page.waitForFunction(()=>hostApp.graph.extra.hutx_workbench?.shots?.length===1);
    const report = await page.evaluate(async () => {
        const prepared = await hostApp.graphToPrompt();
        const output = prepared.output;
        const byType = type => Object.values(output).find(node => node.class_type === type);
        const graphNodes = hostApp.graph._nodes;
        const source = graphNodes.find(node => node.type === 'GHLocalVideoInputDualEngineGH');
        if (!source) throw Error('No dual-engine source was created');
        if (!byType('SaveVideo')?.inputs.video) throw Error('SaveVideo is not connected');
        if (!byType('SamplerCustomAdvanced')?.inputs.latent_image) throw Error('Sampler is not connected');
        if (byType('CreateVideo')?.inputs.fps !== 24) throw Error('Wrong frame rate');
        const roles = graphNodes.find(node => node.type === 'GHMultiSpeechInputGH');
        const role = JSON.parse(roles.widgets.find(widget => widget.name === 'role_A').value);
        if (role.text !== '真实前端参数同步验证。') throw Error('Role text was not synchronized');
        return {nodeTypes: Object.values(output).map(node => node.class_type), frameRate: byType('CreateVideo').inputs.fps, serialized: prepared.workflow};
    });
    assert(report.nodeTypes.includes('GHLocalVideoInputDualEngineGH'));
    await workbench.getByRole('button', {name: '展开', exact: true}).click();
    await page.screenshot({path: path.join(out, 'real-host-generation.png')});
    await workbench.getByRole('tab', {name: /角色与声音/}).click();
    await page.screenshot({path: path.join(out, 'real-host-roles.png')});
    await workbench.getByRole('button', {name: '定位节点', exact: true}).click();
    assert.equal(await page.locator('.hutx-workbench-placeholder').count(), 0);
    await page.evaluate(async workflow => { await hostApp.loadGraphData(workflow); }, report.serialized);
    await workbench.getByRole('tab', {name: /镜头生成/}).click();
    await page.waitForSelector('.hutx-workbench .gh-local-video-root');
    assert.equal(await page.locator('.hutx-workbench .gh-local-video-root').count(), 1);
    assert.equal(await page.evaluate(()=>hostApp.graph.extra.hutx_workbench.shots.length),1);
    // Reloading the same workflow can reuse the graph object and identical node IDs.
    // The open sidebar must follow the new node instance without an extra tab click.
    await page.evaluate(async()=>{
        globalThis.beforeReloadEditor=hostApp.graph._nodes.find(node=>node.type==='GHLocalVideoInputDualEngineGH').hutxWorkbenchPanel.element;
        await hostApp.loadGraphData(hostApp.graph.serialize());
    });
    await page.waitForFunction(()=>{
        const panel=hostApp.graph._nodes.find(node=>node.type==='GHLocalVideoInputDualEngineGH').hutxWorkbenchPanel.element;
        return panel!==beforeReloadEditor&&document.querySelector('.hutx-workbench .gh-local-video-root')===panel;
    });
    if(process.env.HUTX_TEST_ASSEMBLY==='1'){
        await page.evaluate(()=>{hostApp.graph.extra.hutx_workbench.shortlist=[0,1].map(index=>({filename:'api-test-'+index+'.mp4',subfolder:'',type:'output',title:'色卡片段 '+(index+1)}));});
        await workbench.getByRole('tab',{name:/成片管理/}).click();
        await workbench.locator('.wb-clip').first().locator('summary').click();
        await page.waitForFunction(()=>document.querySelector('.wb-clip video')?.readyState>=2);
        for(const [label,value] of [['入点（秒）','0.125'],['出点（秒）','0.375'],['音量（%）','40']]){
            const input=workbench.getByRole('spinbutton',{name:'片段 1 '+label,exact:true});await input.fill(value);await input.press('Tab');
        }
        const savedEdit=await page.evaluate(()=>({workflow:hostApp.graph.serialize(),edit:hostApp.graph.extra.hutx_workbench.shortlist[0].edit}));
        await page.evaluate(async workflow=>{await hostApp.loadGraphData(workflow);},savedEdit.workflow);
        await workbench.getByRole('tab',{name:/成片管理/}).click();
        assert.deepEqual(await page.evaluate(()=>hostApp.graph.extra.hutx_workbench.shortlist[0].edit),savedEdit.edit);
        await page.waitForFunction(()=>document.querySelector('.wb-clip video')?.readyState>=2);
        await workbench.getByRole('button',{name:'展开',exact:true}).click();
        await page.screenshot({path:path.join(out,'real-host-editing.png')});
        await workbench.getByRole('button',{name:'拼接导出 MP4',exact:true}).click();
        await workbench.getByRole('link',{name:'下载拼接成片',exact:true}).waitFor();
        await page.waitForFunction(()=>{const video=document.querySelector('.wb-shortlist>video');return video?.readyState>=2&&video.duration>.7&&video.duration<.9;});
        await page.screenshot({path:path.join(out,'real-host-assembly.png')});
        assert.equal(await page.evaluate(()=>hostApp.graph.extra.hutx_workbench.assembly_job.state),'complete');
    }
    if(process.env.HUTX_LAYOUT_AUDIT){
        if(!(await workbench.evaluate(node=>node.classList.contains('wb-expanded'))))await workbench.getByRole('button',{name:'展开',exact:true}).click();
        for(const width of [1280,390]){
            await page.setViewportSize({width,height:900});
            for(const [kind,title,selector] of [['roles','角色与声音','.hutx-multi-cards'],['generate','镜头生成','.gh-local-video-root']]){
                await workbench.getByRole('tab',{name:new RegExp(title)}).click();
                if(kind==='generate')await workbench.locator('.gh-local-driver').evaluate(node=>node.open=true);
                await workbench.locator(selector).evaluate(node=>node.scrollIntoView({block:'start'}));
                const geometry=await workbench.evaluate(root=>{
                    const content=root.querySelector('.wb-content'),bounds=content.getBoundingClientRect();
                    return {overflow:content.scrollWidth-content.clientWidth,outside:[...root.querySelectorAll('button,input,select,textarea')].filter(node=>node.getClientRects().length&&node.closest('.wb-content')===content).filter(node=>{const r=node.getBoundingClientRect();return r.left<bounds.left-1||r.right>bounds.right+1;}).map(node=>node.getAttribute('aria-label')||node.textContent?.slice(0,40))};
                });
                assert.equal(geometry.overflow,0);assert.deepEqual(geometry.outside,[]);
                await workbench.screenshot({path:path.join(out,`native-layout-${width}-${kind}.png`)});
            }
        }
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(out, 'real-host-verification.txt'), 'PASS: native sidebar registration, actual node creation, widget synchronization, graphToPrompt, 24fps, workflow reload. No inference or paid provider request.\n');
    console.log('PASS: real ComfyUI workbench registration, native graph and workflow reload');
} finally { await browser.close(); }
