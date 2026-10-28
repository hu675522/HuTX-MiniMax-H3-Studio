import {app} from '/scripts/app.js';
import {api} from '/scripts/api.js';
import {VIDEO_NODE_TYPES, SPEECH_NODE_TYPES, graphNodes, widgetValue, videoKey, videoUrl, videoIdentity, readWorkbenchState, writeWorkbenchState, validateGeneration, connectRoleAudio, hasVideoOutput, leasePanel} from './workbench_state.js';
import {createWorkbenchNode, addStarterPipeline, engineLabel} from './workbench_graph.js';
import {installWorkbenchTheme} from './workbench_theme.js';
import {captureShot,createSequenceRunner} from './workbench_sequence.js';
import {createClipEditor,sequenceDuration,timeLabel} from './workbench_edit.js';
import {createExecutionProgress,createQueueProgressSync} from './workbench_progress.js';
import {dualEngineBranchState,setDualEngineBranch} from './dual_engine_switches.js';

const TAB_ID = 'hutx-studio-workbench';
const PAGES = {
    roles: ['01', '角色与声音', '生成、试听并采用口播', ['生成 · 试听', '采用口播']],
    generate: ['02', '镜头生成', '设置素材与提示词，生成镜头', ['素材 · 提示词', '生成镜头']],
    results: ['03', '成片管理', '预览、下载和整理成片', ['预览 · 下载', '整理成片']],
};
function element(tag, cls = '', text = '') {
    const result = document.createElement(tag); result.className = cls; result.textContent = text; return result;
}
function button(text, action, cls = '') {
    const result = element('button', cls, text); result.type = 'button'; result.onclick = action; return result;
}

export function createWorkbench({app: host = app, api: client = api} = {}) {
    installWorkbenchTheme();
    const root = element('section', 'hutx-workbench'); root.setAttribute('aria-label', 'HuTX总台');
    const header = element('header', 'wb-header'), brand = element('div', 'wb-brand');
    const pageContext=element('div','wb-page-context');
    const pageEyebrow=element('span','wb-page-eyebrow'),pageTitle=element('strong','wb-page-title');
    pageContext.append(pageEyebrow,pageTitle);
    brand.append(element('strong', '', 'HuTX STUDIO'), element('small', 'wb-tagline', '声音 · 镜头 · 成片'));
    const expand = button('展开', () => toggleExpanded()); expand.title = '展开或收起工作台'; expand.setAttribute('aria-expanded', 'false');
    header.append(element('div', 'wb-mark', 'H'), brand,pageContext, expand);
    const project = element('div', 'wb-project'), projectLabel = element('label', '', '当前项目');
    const projectName = element('input'); projectName.maxLength = 120; projectName.setAttribute('aria-label', '项目名称');
    projectLabel.append(projectName); project.append(projectLabel, element('span', 'wb-version', '工作台预览 0.3'));
    const tabs = element('nav', 'wb-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '工作台页面');
    const content = element('div', 'wb-content'); content.id = 'hutx-workbench-content'; content.setAttribute('role', 'tabpanel');
    const bottom = element('footer', 'wb-bottom'), status = element('div', 'wb-status', '选择页面，开始制作。'); status.setAttribute('role', 'status');
    const progressBox = element('div','wb-execution-progress'); progressBox.hidden = true;
    const progressHeading = element('div','wb-progress-heading'), progressTitle = element('span','wb-progress-title'), progressDetail = element('span','wb-progress-detail');
    progressHeading.append(progressTitle,progressDetail);
    const progressBar = element('progress','wb-progress-bar'); progressBar.max = 100; progressBar.setAttribute('aria-label','当前 ComfyUI 节点进度');
    progressBox.append(progressHeading,progressBar);
    const refinementSlot=element('div','wb-refinement-slot');refinementSlot.hidden=true;
    const runArea = element('div','wb-run-area'); runArea.hidden = true;
    const run = button('运行当前画布',() => runAction(queueGeneration)(),'wb-primary wb-run'); run.dataset.action = 'generate';
    run.title = '运行当前画布中的输出节点。多个保存线路会一起执行；模型家族与参考音频仍按节点设置校验。';
    runArea.append(run);
    bottom.append(progressBox,refinementSlot,runArea,status); root.append(header, project, tabs, content, bottom);
    const selections = new WeakMap(), listeners = [];
    const clipDurations=new Map(),openClips=new Set();
    let page = 'roles', graph = null, lease = null, nodeHost = null, editorNode = null, mount = null, destroyed = false;
    let signature = '', returned = false, submitting = false, expanded = false;
    let deletingKey='',deleteCandidate='';
    let mediaRevision=0;
    let records = [], historyBusy = false, historyLoaded = false, historyError = '', historyAbort = null, refreshTimer = null;
    let projectEditGraph = null, projectEditId='';
    const executionProgress = createExecutionProgress();
    let sequenceProject = '', sequenceGraph = null, assembly = null, assemblyTimer = null, assemblyTracking='',assemblyEpoch=0,renderedProject='',assemblySubmitting=false;
    const setStatus = (text, state = '') => { if (!destroyed) { status.textContent = text; status.dataset.state = state; } };
    let reportedExecution='';
    const queueSync=createQueueProgressSync({api:client,progress:executionProgress,isVisible:()=>Boolean(mount?.isConnected&&mount.getClientRects().length),onUpdate:()=>{reportExecution();updateProgress();}});
    const currentGraph = () => host.graph;
    const selection = () => {
        const value = currentGraph();
        if (!value) return {};
        if (!selections.has(value)) selections.set(value, {});
        return selections.get(value);
    };
    const nodesFor = kind => graphNodes(currentGraph()).filter(node => (kind === 'roles' ? SPEECH_NODE_TYPES : VIDEO_NODE_TYPES).has(node.type));
    const selectedNode = kind => {
        const nodes = nodesFor(kind), chosen = selection()[kind];
        return nodes.find(node => String(node.id) === String(chosen)) || nodes[0] || null;
    };
    const release = () => { lease?.release(); lease = null; };
    const runAction = action => async () => { try { await action(); } catch (error) { setStatus(error.message || '操作失败，请检查当前工作流。', 'error'); } };
    const sequence = createSequenceRunner({api:client,getGraph:currentGraph,getPrepared:()=>host.graphToPrompt(),
        isCurrent:()=>!destroyed&&currentGraph()===sequenceGraph&&readWorkbenchState(currentGraph()).project_id===sequenceProject,
        onUpdate:(id,patch)=>{
            if(destroyed||currentGraph()!==sequenceGraph||readWorkbenchState(currentGraph()).project_id!==sequenceProject)return;
            const state=readWorkbenchState(sequenceGraph),shots=state.shots.map(shot=>shot.id===id?{...shot,...patch}:shot);
            writeWorkbenchState(sequenceGraph,{...state,shots});
            if(page==='generate')render();
        },onState:(state,shot)=>{
            if(destroyed)return;
            if(state==='running')setStatus(`正在逐段生成：${shot.title}。结果按本镜头任务编号收集。`,'running');
            if(state==='stopping')setStatus('当前镜头将继续完成；不会再提交后续镜头。','running');
            if(state==='preparing')setStatus('正在检查镜头快照与当前线路…','running');
            if(state==='stopped')setStatus('已停止后续镜头，完成结果已保存。','success');
            if(state==='settled'&&page==='generate')render();
        }});

    projectName.onfocus = () => { projectEditGraph = currentGraph();projectEditId=readWorkbenchState(currentGraph()).project_id; };
    projectName.onchange = runAction(() => {
        const active = currentGraph();
        if (projectEditGraph && (projectEditGraph !== active || projectEditId!==readWorkbenchState(active).project_id)) throw new Error('工作流已切换，请重新填写项目名称。');
        writeWorkbenchState(active, {...readWorkbenchState(active), project_name: projectName.value.trim() || '未命名项目'});
        setStatus('项目名称已更新；保存 ComfyUI 工作流即可保留。', 'success');
    });
    for (const [key, [number, name]] of Object.entries(PAGES)) {
        const tab = button('', () => selectPage(key)); tab.setAttribute('role', 'tab'); tab.id = `hutx-wb-tab-${key}`;
        tab.setAttribute('aria-controls', content.id); tab.dataset.page = key;
        tab.append(element('small', '', number), element('span', '', name)); tabs.append(tab);
        tab.onkeydown = event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const keys = Object.keys(PAGES), index = keys.indexOf(page);
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? keys.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + keys.length) % keys.length;
            selectPage(keys[next]); tabs.children[next].focus();
        };
    }
    function toggleExpanded(force = !expanded) {
        expanded = force; root.classList.toggle('wb-expanded', expanded); expand.textContent = expanded ? '收起' : '展开';
        expand.setAttribute('aria-expanded', String(expanded));
        if (expanded) document.body.append(root); else if (mount?.isConnected) mount.append(root);
    }
    root.addEventListener('keydown', event => { if (event.key === 'Escape' && expanded && !event.defaultPrevented) { event.preventDefault(); toggleExpanded(false); } });
    function pauseVideos() { for (const video of root.querySelectorAll('video')) video.pause(); }
    function selectPage(next) {
        if (!PAGES[next]) return;
        pauseVideos(); release(); page = next; returned = false; signature = ''; render();
        if (next === 'results' && !historyLoaded) refreshHistory();
    }
    function focusNode(node) {
        if (!node) return;
        toggleExpanded(false); release(); returned = true; render();
        host.canvas?.selectNode?.(node); host.canvas?.centerOnNode?.(node); host.canvas?.setDirty?.(true, true);
        setStatus('已返回画布面板；可点击「在工作台编辑」继续。');
    }
    function mountEditor(node) {
        if (!nodeHost || !node) return;
        editorNode=node;
        if (returned) { nodeHost.append(button('在工作台编辑', runAction(() => { returned = false; render(); if(lease)setStatus('已恢复工作台编辑，参数与画布同步。','success'); }), 'wb-primary')); return; }
        try { lease = leasePanel(node, nodeHost, () => { lease = null; returned = true; render(); }); }
        catch (error) { nodeHost.append(element('p', 'wb-hint', error.message), button('重新连接面板', () => {returned=false;render();if(lease)setStatus('已重新连接节点编辑器。','success');})); }
    }
    function empty(title, description, label, action) {
        const box = element('div', 'wb-empty'); box.append(element('strong', '', title), element('p', '', description));
        if (label) box.append(button(label, runAction(action), 'wb-primary')); content.append(box);
    }
    function chooseNode(kind) {
        const list = nodesFor(kind), node = selectedNode(kind), toolbar = element('div', 'wb-toolbar'), label = element('label', '', kind === 'roles' ? '画布中的口播节点' : '当前镜头节点');
        const select = element('select'); select.setAttribute('aria-label', kind === 'roles' ? '选择口播节点' : '选择镜头节点');
        for (const candidate of list) {
            const name = kind === 'roles' ? (candidate.type === 'GHMultiSpeechInputGH' ? 'HuTX_多角色口播' : 'HuTX_单角色口播') : candidate.title || candidate.type;
            select.append(new Option(`${name} · #${candidate.id}`, String(candidate.id)));
        }
        select.value = String(node?.id || '');
        select.onchange = () => { selection()[kind] = select.value; returned = false; render(); };
        label.append(select); toolbar.append(label, button('定位节点', () => focusNode(node), 'wb-quiet'));
        if (kind === 'generate') {
            toolbar.classList.add('wb-toolbar-generation');
            const meta = element('div','wb-node-meta'); meta.dataset.summary = 'generation'; meta.setAttribute('aria-label','当前镜头设置'); toolbar.append(meta);
        }
        content.append(toolbar);
        return node;
    }
    function addSpeech() {
        const active = currentGraph(); if (!active) throw new Error('请先打开一个工作流。');
        const node = createWorkbenchNode(active, 'GHMultiSpeechInputGH'); selection().roles = node.id; returned = false; render();
        setStatus('已添加三角色卡。生成和采用操作会同步到画布节点。', 'success');
    }
    function addPipeline() {
        const active = currentGraph(); if (!active) throw new Error('请先打开一个工作流。');
        const selected = selectedNode('generate');
        const existing = selected?.type === 'GHLocalVideoInputDualEngineGH' && !hasVideoOutput(active, selected) ? selected : null;
        const node = addStarterPipeline(active, existing); selection().generate = node.id; returned = false; render();
        setStatus('已添加基础单采线路。请确认模型、素材和提示词，再运行；已有节点保留。', 'success');
    }
    function renderRoles() {
        if (!nodesFor('roles').length) { empty('先创建您的角色', '一个节点包含 A / B / C 三张角色卡，也支持选择已有单人口播节点。', '添加三角色口播', addSpeech); return; }
        const node = chooseNode('roles'), actions = element('div', 'wb-actions');
        actions.append(button('添加角色组', runAction(addSpeech), 'wb-quiet'));
        if (node.type === 'GHMultiSpeechInputGH') actions.append(button('连接到当前镜头三槽音频', runAction(() => {
            const target = selectedNode('generate');
            if (!target) throw new Error('请先到「镜头生成」添加或选择视频节点。');
            connectRoleAudio(currentGraph(), node, target);
            const mode = target.hutxWorkbenchPanel?.element?.querySelector('.gh-cloud-modes button[value="all_reference"]');
            if (mode) mode.click(); else {
                const targetWidget = target.widgets?.find(item => item.name === 'main_mode');
                if (targetWidget) { targetWidget.value = 'all_reference'; targetWidget.callback?.('all_reference'); }
            }
            setStatus('A / B / C 已接入参考音频槽 1 / 2 / 3，并切换全能参考。请先采用各角色音频；三路同时测试建议先用 4 秒镜头。', 'success');
        }), 'wb-primary'));
        content.append(actions); nodeHost = element('div', 'wb-panel-host'); content.append(nodeHost); mountEditor(node);
    }
    function renderGenerate() {
        if (!nodesFor('generate').length) { empty('准备第一个镜头', '已有双引擎工作流会自动显示。也可以添加一条采样、解码和保存齐全的基础单采线路。', '添加基础单采线路', addPipeline); return; }
        const node = chooseNode('generate'); updateSummary();renderRefinements(node);
        const actions = element('div', 'wb-actions');
        if (!hasVideoOutput(currentGraph(), node)) actions.append(button('补齐基础单采线路', runAction(addPipeline)));
        if(actions.childElementCount)content.append(actions);
        renderShots(node);
        nodeHost = element('div', 'wb-panel-host'); nodeHost.style.marginTop = '16px'; content.append(nodeHost); mountEditor(node);
    }
    async function queueGeneration() {
        if (submitting || sequence.busy) throw new Error('逐段任务或画布提交正在运行，请等待完成。');
        if (['queued','running'].includes(executionProgress.snapshot().phase)) throw new Error('ComfyUI 已有任务排队或执行中，请等待完成，避免重复提交。');
        const active = currentGraph(), node = selectedNode('generate'), originPage=page;
        validateGeneration(active, node);
        for (const speech of nodesFor('roles')) {
            const panel = speech.hutxWorkbenchPanel;
            if (panel?.controller?.busy || panel?.roles?.some(role => role.panel.controller.busy)) throw new Error('口播正在生成，请等待完成并采用后再运行视频。');
        }
        submitting = true;
        executionProgress.submitting(); updateProgress();
        for (const current of root.querySelectorAll('[data-action=generate]')) {current.disabled = true;current.textContent = '正在提交…';}
        setStatus('正在检查素材并提交当前画布…', 'running');
        try {
            await node.hutxWorkbenchPanel?.ready?.();
            if (currentGraph() !== active) throw new Error('工作流已切换，本次提交已停止。');
            validateGeneration(active, node);
            if(host.processingQueue)throw new Error('ComfyUI 正在提交其它任务，请稍后重试。');
            const accepted = await host.queuePrompt(0, 1);
            if (accepted === false) throw new Error('ComfyUI 未接受本次提交，请查看画布错误提示或队列状态。');
            executionProgress.queued(); updateProgress();
            if (executionProgress.snapshot().phase === 'queued') setStatus('已提交，等待 ComfyUI 执行；下方会显示当前节点进度。', 'running');
            if(currentGraph()===active&&page===originPage){historyLoaded=false;selectPage('results');}
        } catch (error) {
            executionProgress.rejected(error.message || '提交失败。'); updateProgress(); throw error;
        } finally {
            submitting = false;
            updateProgress();
        }
    }
    async function saveCurrentShot(replaceId=null) {
        if(sequence.busy||submitting)throw new Error('逐段任务运行时不能修改镜头快照。');
        const active=currentGraph(),source=selectedNode('generate');validateGeneration(active,source);
        await source.hutxWorkbenchPanel?.ready?.();
        const prepared=await host.graphToPrompt();
        if(currentGraph()!==active)throw new Error('工作流已切换，未保存镜头。');
        const state=readWorkbenchState(active),previous=state.shots.find(shot=>shot.id===replaceId);
        const shot=captureShot(prepared,source.id,previous?.title||`镜头 ${state.shots.length+1}`);
        if(replaceId)shot.id=replaceId;
        const shots=replaceId?state.shots.map(item=>item.id===replaceId?shot:item):[...state.shots,shot];
        writeWorkbenchState(active,{...state,shots});render();
        setStatus('镜头设置已保存。批量生成使用这些快照，不改写画布；需要优化的提示词请先优化再保存。','success');
    }
    function updateShot(id,patch,expected=currentGraph()) {
        if(sequence.busy||currentGraph()!==expected)throw new Error('任务运行中或项目已切换，未修改镜头。');
        const state=readWorkbenchState(expected);
        writeWorkbenchState(expected,{...state,shots:state.shots.map(shot=>shot.id===id?{...shot,...patch}:shot)});
    }
    function renderShots(source) {
        const active=currentGraph(),state=readWorkbenchState(active),section=element('section','wb-shots');
        const heading=element('div','wb-result-summary');heading.append(element('h3','',`镜头列表 · ${state.shots.length}`));
        const save=button('将当前设置保存为镜头',runAction(()=>saveCurrentShot()),'wb-primary');save.disabled=sequence.busy;heading.append(save);section.append(heading);
        section.append(element('p','wb-hint','每段保存提示词、时长、模型、素材、已采用口播、种子与分支开关；其余下游参数共用当前画布。'));
        if(state.shots.length){
            const batch=element('div','wb-actions'),start=button('逐段生成未完成镜头',runAction(async()=>{
                if(sequence.busy||submitting)throw new Error('生成任务正在提交。');
                const current=readWorkbenchState(currentGraph());
                if(!current.project_id)throw new Error('请先保存镜头。');
                sequenceGraph=currentGraph();sequenceProject=current.project_id;
                await sequence.start(current.shots);
                if(currentGraph()===sequenceGraph&&readWorkbenchState(currentGraph()).project_id===sequenceProject){setStatus('逐段生成结束，完成结果已绑定各镜头，可选入成片。','success');historyLoaded=false;}
            }),'wb-primary');start.disabled=sequence.busy;
            const stop=button('停止后续镜头',()=>sequence.stopAfterCurrent());stop.disabled=!sequence.busy;batch.append(start,stop);section.append(batch);
            if(state.shots.some(shot=>shot.results.length))batch.append(button('按镜头顺序选入成片',runAction(()=>{
                const latest=readWorkbenchState(active),ordered=[],keys=new Set();
                for(const shot of latest.shots)for(const file of shot.results)if(!keys.has(videoKey(file))){keys.add(videoKey(file));const existing=latest.shortlist.find(item=>videoKey(item)===videoKey(file));ordered.push({...file,title:shot.title,...(existing?{edit:existing.edit}:{})});}
                saveShortlist([...ordered,...latest.shortlist.filter(file=>!keys.has(videoKey(file)))],active);setStatus('已按镜头列表顺序整理待拼接片段。','success');
            })));
        }
        const states={draft:'待生成',queued:'已排队',running:'生成中',complete:'已完成',error:'失败，可重试',unknown:'状态待确认'};
        state.shots.forEach((shot,index)=>{
            const row=element('details','wb-shot');row.open=state.shots.length===1;
            const summary=element('summary');summary.append(element('span','',`${String(index+1).padStart(2,'0')} · ${shot.title}`),element('span','wb-chip',states[shot.state]));row.append(summary);
            const title=element('input');title.value=shot.title;title.maxLength=120;title.setAttribute('aria-label',`镜头 ${index+1} 名称`);title.disabled=sequence.busy;
            title.onchange=runAction(()=>updateShot(shot.id,{title:title.value},active));
            const prompt=element('textarea','wb-shot-prompt');prompt.value=shot.source_inputs.prompt;prompt.setAttribute('aria-label',`镜头 ${index+1} 提示词`);prompt.disabled=sequence.busy;
            prompt.onchange=runAction(()=>{
                const latest=readWorkbenchState(active).shots.find(item=>item.id===shot.id);
                const sourceInputs={...latest.source_inputs,prompt:prompt.value};
                if(sourceInputs.gh_local_state_json){const local=JSON.parse(sourceInputs.gh_local_state_json);local.prompt=prompt.value;sourceInputs.gh_local_state_json=JSON.stringify(local);}
                updateShot(shot.id,{source_inputs:sourceInputs,state:'draft',prompt_id:'',results:[],error:''},active);
            });
            const duration=element('input');duration.type='number';duration.min='2';duration.max='30';duration.step='1';duration.value=shot.source_inputs.duration_seconds;duration.disabled=sequence.busy;duration.setAttribute('aria-label',`镜头 ${index+1} 时长`);
            duration.onchange=runAction(()=>{const latest=readWorkbenchState(active).shots.find(item=>item.id===shot.id);updateShot(shot.id,{source_inputs:{...latest.source_inputs,duration_seconds:Number(duration.value)},state:'draft',prompt_id:'',results:[],error:''},active);});
            const durationLabel=element('label','wb-hint','时长（秒）');durationLabel.append(duration);
            row.append(title,prompt,durationLabel,element('div','wb-hint',`${shot.source_inputs.engine_mode==='hyperflow'?'HyperFlow':'Fused / Local'} · 来源节点 #${shot.source_id}`));
            if(shot.prompt_id)row.append(element('div','wb-hint','任务：'+shot.prompt_id));
            if(shot.error)row.append(element('p','wb-video-error',shot.error));
            const actions=element('div','wb-actions');
            for(const [delta,text] of [[-1,'上移'],[1,'下移']]){
                const move=button(text,runAction(()=>{const next=[...readWorkbenchState(active).shots];[next[index],next[index+delta]]=[next[index+delta],next[index]];if(active!==currentGraph())throw new Error('项目已切换。');writeWorkbenchState(active,{...readWorkbenchState(active),shots:next});render();}));
                move.disabled=sequence.busy||index+delta<0||index+delta>=state.shots.length;actions.append(move);
            }
            const replace=button('用当前设置更新',runAction(()=>saveCurrentShot(shot.id)));replace.disabled=sequence.busy;actions.append(replace);
            const remove=button('删除镜头',runAction(()=>{if(sequence.busy||active!==currentGraph())throw new Error('项目已切换或任务正在运行。');writeWorkbenchState(active,{...readWorkbenchState(active),shots:readWorkbenchState(active).shots.filter(item=>item.id!==shot.id)});render();}));remove.disabled=sequence.busy;actions.append(remove);
            if(shot.results.length)actions.append(button('选入成片',runAction(()=>{
                const latest=readWorkbenchState(active),keys=new Set(latest.shortlist.map(videoKey));
                saveShortlist([...latest.shortlist,...shot.results.filter(file=>!keys.has(videoKey(file))).map(file=>({...file,title:shot.title}))],active);setStatus('镜头结果已选入待拼接清单。','success');
            })));
            row.append(actions);section.append(row);
        });
        content.append(section);
    }
    function updateSummary() {
        const meta = content.querySelector('[data-summary=generation]'), node = selectedNode('generate');
        if (!meta || !node) return;
        const labels = [engineLabel(node), `${widgetValue(node, 'duration_seconds') || 5} 秒`, hasVideoOutput(currentGraph(), node) ? '已连接保存线路' : '待连接保存线路'];
        if (meta.textContent === labels.join('')) return;
        meta.replaceChildren(...labels.map(text => element('span', 'wb-chip', text)));
    }
    function renderRefinements(node){
        if(node.type!=='GHLocalVideoInputDualEngineGH')return;
        const area=element('fieldset','wb-refinements');area.append(element('legend','','画面精修'));
        for(const [kind,name] of [['second','二采精修'],['face','VOSR2 修脸']]){
            const label=element('label'),input=element('input');input.type='checkbox';input.dataset.branch=kind;input.setAttribute('aria-label',name);
            input.onchange=runAction(()=>{
                if(currentGraph()!==node.graph||selectedNode('generate')!==node)throw new Error('镜头已切换，请重新选择。');
                if(submitting||sequence.busy||['queued','running'].includes(executionProgress.snapshot().phase))throw new Error('任务运行中，请完成后再调整精修开关。');
                try{setDualEngineBranch(node,kind,input.checked);setStatus(`${name}已${input.checked?'开启':'关闭'}，与画布开关同步。`,'success');}
                finally{updateRefinements();}
            });
            label.append(input,element('span','',name));area.append(label);
        }
        const hint=element('span','wb-hint');hint.dataset.refinementHint='';area.append(hint);refinementSlot.append(area);refinementSlot.hidden=false;updateRefinements();
    }
    function updateRefinements(){
        const area=refinementSlot.querySelector('.wb-refinements'),node=selectedNode('generate');if(!area||!node)return;
        const fused=widgetValue(node,'engine_mode')==='fused_turbo',busy=submitting||sequence.busy||['queued','running'].includes(executionProgress.snapshot().phase);
        const missing=[];
        for(const input of area.querySelectorAll('[data-branch]')){
            const state=dualEngineBranchState(node,input.dataset.branch);
            input.checked=state.value;input.disabled=!fused||busy||!state.available;
            input.closest('label').title=!fused?'HyperFlow 模式按原规则关闭精修。':state.reason||'同步现有画布开关，不改变接线。';
            if(!state.available)missing.push(input.getAttribute('aria-label'));
        }
        area.querySelector('[data-refinement-hint]').textContent=!fused?'HyperFlow 模式关闭精修。':missing.length?`${missing.join('、')}线路未就绪；请在画布确认。`:'初稿可关闭，精修时再开启。';
    }
    function updateProgress() {
        if (destroyed) return;
        const state = executionProgress.snapshot(), active = ['submitting','queued','running','unknown'].includes(state.phase);
        const busy=submitting||sequence.busy||['queued','running'].includes(state.phase);
        for(const current of root.querySelectorAll('[data-action=generate]')) {
            current.disabled=busy;
            current.textContent=submitting?'正在提交…':state.phase==='running'?'任务执行中…':state.phase==='queued'?'等待队列执行…':current===run?'运行当前画布':'重新生成当前镜头';
        }
        updateRefinements();
        progressBox.hidden = state.phase === 'idle' && !state.connectionLost; progressBox.dataset.state = state.phase;
        const title = {submitting:'正在提交当前画布…',queued:'等待队列执行…',running:'ComfyUI 正在执行',complete:'任务已完成',error:'任务失败',interrupted:'任务已中断'}[state.phase] || '';
        const node = graphNodes(currentGraph()).find(node => String(node.id) === state.nodeId);
        progressTitle.textContent = state.connectionLost ? '无法同步 ComfyUI 状态，请检查服务或连接' : state.phase === 'unknown' ? state.message : state.phase === 'running' ? (state.message || (state.nodeId ? `正在处理 · ${node?.title || node?.type || `节点 #${state.nodeId}`}` : title)) : title;
        progressTitle.title = state.message || progressTitle.textContent;
        const percent = state.max ? Math.round(state.value / state.max * 100) : null;
        const elapsed = `${state.recovered?'跟踪 ':''}${Math.floor(state.elapsedMs / 1000)} 秒`;
        progressDetail.textContent = state.phase === 'running' && percent != null ? `${state.value} / ${state.max} · ${percent}% · ${elapsed}` : `${elapsed}${state.phase === 'queued' && state.queueRemaining > 0 ? ` · 队列 ${state.queueRemaining}` : ''}`;
        if(state.connectionLost)progressBar.removeAttribute('value');
        else if (state.phase === 'complete') progressBar.value = 100;
        else if (percent != null) progressBar.value = percent;
        else if (active) progressBar.removeAttribute('value');
        else progressBar.value = 0;
        progressBar.setAttribute('aria-valuetext',state.connectionLost || state.phase==='unknown' ? progressTitle.textContent : state.phase === 'running' && percent != null ? `当前节点 ${percent}%，${state.value} / ${state.max} 步` : title);
        progressBox.title = `显示当前 ComfyUI 任务的节点进度；节点完成后还可能继续解码、修复或保存。${state.promptId?' 任务编号：'+state.promptId:''}`;
    }
    function reportExecution() {
        const state=executionProgress.snapshot(),key=state.promptId+':'+state.phase;
        if(key===reportedExecution)return;reportedExecution=key;
        if(state.phase==='running')setStatus('后端任务正在执行。未显示步数时，仍可能处于模型加载或当前节点计算中。','running');
        if(state.phase==='unknown')setStatus(state.message,'warning');
        if(state.phase==='error')setStatus('执行失败：'+state.message,'error');
        if(state.phase==='interrupted')setStatus('本次队列执行已中断。');
        if(state.phase==='complete'){setStatus('队列执行完成，可前往成片管理查看。','success');scheduleHistory();}
    }
    function saveShortlist(shortlist, expectedGraph = currentGraph(), expectedProject=readWorkbenchState(expectedGraph).project_id) {
        const active = currentGraph();
        if (expectedGraph !== active || expectedProject!==readWorkbenchState(active).project_id) throw new Error('工作流已切换，请刷新成片页后重试。');
        if(assemblySubmitting||readWorkbenchState(active).assembly_job?.state==='running')throw new Error('请等待或取消当前拼接，再修改片段。');
        if(shortlist.length>100)throw new Error('待拼接清单最多保存 100 个片段。');
        writeWorkbenchState(active, {...readWorkbenchState(active), shortlist,assembly_job:null}); render();
    }
    function exportShortlist() {
        const state = readWorkbenchState(currentGraph());
        const blob = new Blob([JSON.stringify({format: 'hutx-workbench/3', ...state}, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob), link = element('a'); link.href = url; link.download = 'HuTX-片段清单.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        setStatus('已导出片段顺序、裁剪与声音参数。视频文件请单独下载。', 'success');
    }
    function renderResults() {
        const resultGraph = currentGraph(), state = readWorkbenchState(resultGraph), list = state.shortlist;
        const resultProject=state.project_id;
        assembly=state.assembly_job;
        const editingLocked=assemblySubmitting||assembly?.state==='running'||Boolean(deletingKey)||sequence.busy;
        if(assembly?.state==='running'&&assemblyTracking!==assembly.job_id)trackAssembly(assembly.job_id,resultGraph,state.project_id);
        if (list.length) {
            const shortlist = element('section', 'wb-shortlist'); shortlist.append(element('h3', '', `待拼接片段 · ${list.length}`), element('div', 'wb-hint', '按顺序裁剪与拼接，保留原文件。支持 1–32 段、同分辨率、累计 10 分钟；导出 24fps MP4。'));
            const durationSummary=element('p','wb-duration-summary');durationSummary.setAttribute('aria-live','polite');
            const refreshDuration=()=>{
                const total=sequenceDuration(list,file=>clipDurations.get(videoKey(file)));
                durationSummary.textContent=`预计成片 ${timeLabel(total.seconds)}${total.unknown?` · ${total.unknown} 段时长待读取`:''}${total.invalid?` · ${total.invalid} 段裁剪无效`:''}${total.seconds>600?' · 超过 10 分钟上限':''}`;
            };refreshDuration();shortlist.append(durationSummary);
            list.forEach((file, index) => {
                const container=element('article','wb-edit-clip'),key=videoKey(file);
                const row = element('div', 'wb-short-item'); row.append(element('span', '', `${String(index + 1).padStart(2, '0')}  ${file.title}`));
                for (const [delta, text] of [[-1, '↑'], [1, '↓']]) {
                    const move = button(text, runAction(() => { const next = [...list]; [next[index], next[index + delta]] = [next[index + delta], next[index]]; saveShortlist(next, resultGraph,resultProject); }));
                    move.disabled = editingLocked||index + delta < 0 || index + delta >= list.length; move.setAttribute('aria-label', `${text === '↑' ? '上移' : '下移'}片段 ${index + 1}`); row.append(move);
                }
                const remove=button('移除', runAction(() => saveShortlist(list.filter((_, i) => i !== index), resultGraph,resultProject)));remove.disabled=editingLocked;row.append(remove);
                const editor=createClipEditor(file,index,{url:videoUrl(client,file),disabled:editingLocked,open:openClips.has(key),onToggle:open=>open?openClips.add(key):openClips.delete(key),
                    onDuration:duration=>{if(!container.isConnected)return;clipDurations.set(key,duration);refreshDuration();},
                    pauseOthers:video=>{root.querySelectorAll('video').forEach(other=>{if(other!==video)other.pause();});},
                    onChange:edit=>{openClips.add(key);saveShortlist(list.map(item=>videoKey(item)===key?{...item,edit}:item),resultGraph,resultProject);setStatus('片段编辑已保存，重新导出后生效。原视频保持完整。','success');}
                });
                if(deletingKey===key){const preview=editor.querySelector('video');preview.removeAttribute('src');preview.load();}
                container.append(row,editor);shortlist.append(container);
            });
            const actions = element('div', 'wb-actions'),assemble=button(assembly?.state==='running'?'正在拼接…':'拼接导出 MP4',runAction(startAssembly),'wb-primary');
            assemble.disabled=editingLocked||list.length>32;actions.append(assemble,button('导出片段清单', exportShortlist));
            if(assembly?.state==='running')actions.append(button('取消拼接',runAction(async()=>{await assemblyRequest(`/assemble/${assembly.job_id}/cancel`,{method:'POST'});})));shortlist.append(actions);content.append(shortlist);
        }
        if(assembly?.state==='running')content.append(element('p','wb-hint',`拼接进度：${assembly.completed} / ${assembly.total}`));
        if(assembly?.state==='complete'&&assembly.result){
            const box=element('section','wb-shortlist'),video=element('video');video.controls=true;video.preload='metadata';video.src=videoUrl(client,assembly.result);video.style.width='100%';
            const download=element('a','wb-button','下载拼接成片');download.href=videoUrl(client,assembly.result,true);download.download=assembly.result.filename;
            const resultHeading=element('div','wb-result-summary');resultHeading.append(element('h3','','拼接成片'),download);
            box.append(resultHeading,video);content.append(box);
        }
        const heading = element('div', 'wb-result-summary'); heading.append(element('h3', '', `本机 HuTX 历史 · ${records.length}`), button(historyBusy ? '读取中…' : '刷新', () => refreshHistory())); content.append(heading);
        if (selectedNode('generate')) {
            const actions = element('div', 'wb-actions'), rerun = button('重新生成当前镜头', runAction(queueGeneration));
            rerun.dataset.action = 'generate'; rerun.disabled = submitting; actions.append(rerun, button('查看当前镜头设置', () => selectPage('generate'), 'wb-quiet')); content.append(actions);
        }
        if (historyError) content.append(element('p', 'wb-hint', historyError));
        if (!records.length) { empty(historyBusy ? '正在读取历史…' : '还没有可用成片', '完成 HuTX 视频生成后在这里刷新。这里只显示执行历史中可定位的本机视频文件。'); return; }
        const gallery = element('div', 'wb-result-list'); content.append(gallery);
        const keys = new Set(list.map(videoKey));
        for (const file of records) {
            const card = element('article', 'wb-video-card'), video = element('video'); video.controls = true; video.preload = 'metadata'; video.playsInline = true; if(deletingKey!==videoKey(file))video.src = videoUrl(client, file); video.setAttribute('aria-label', file.title);
            const error = element('div', 'wb-video-error', '无法预览：文件可能已移动或当前浏览器不支持该格式。'); error.hidden = true; video.onerror = () => { error.hidden = false; };
            const meta = element('div', 'wb-video-meta'); meta.append(element('strong', '', file.title), element('small', '', `${file.type === 'temp' ? '临时文件' : '输出文件'} · 来源节点 #${file.nodeId}`));
            const actions = element('div', 'wb-video-actions'), download = element('a', 'wb-button', '下载视频'); download.href = videoUrl(client, file, true); download.download = file.filename.split('/').at(-1);
            const chosen = keys.has(videoKey(file));
            const pick = button(chosen ? '✓ 已选入片段' : '选入待拼接', runAction(() => {
                const latest = readWorkbenchState(currentGraph()).shortlist;
                const key = videoKey(file), present = latest.some(item => videoKey(item) === key);
                if (!present && latest.length >= 100) throw new Error('待拼接清单最多保留 100 个片段。');
                saveShortlist(present ? latest.filter(item => videoKey(item) !== key) : [...latest, file], resultGraph,resultProject);
            })); pick.disabled=editingLocked;pick.setAttribute('aria-pressed', String(chosen)); actions.append(download, pick);
            const key=videoKey(file),deleteActions=element('div','wb-delete-actions');
            if(deleteCandidate===key){
                meta.append(element('p','wb-delete-note','永久删除此视频文件？'));
                const confirm=button('确认删除',runAction(()=>deleteVideo(file,resultGraph,resultProject)),'wb-danger');
                confirm.disabled=editingLocked;confirm.title=`永久删除 ${file.filename}`;
                deleteActions.append(confirm,button('取消',()=>{deleteCandidate='';render();},'wb-quiet'));
            }else{
                const remove=button(deletingKey===key?'删除中…':'删除',()=>{deleteCandidate=key;render();},'wb-danger');
                remove.disabled=editingLocked;remove.title='删除本机视频文件，并移除当前项目中的相关引用';deleteActions.append(remove);
            }
            actions.append(deleteActions);meta.append(actions); card.append(video, error, meta); gallery.append(card);
        }
    }
    async function deleteVideo(file,expectedGraph,expectedProject) {
        if(deletingKey||sequence.busy||assemblySubmitting||readWorkbenchState(expectedGraph).assembly_job?.state==='running')throw new Error('任务正在使用视频，请完成后再删除。');
        if(expectedGraph!==currentGraph()||readWorkbenchState(expectedGraph).project_id!==expectedProject)throw new Error('工作流已切换，请刷新列表后重试。');
        const key=videoKey(file);deletingKey=key;deleteCandidate='';
        // Release browser file handles before asking Windows to remove the video.
        for(const video of root.querySelectorAll('video'))if(video.getAttribute('src')===videoUrl(client,file)){video.pause();video.removeAttribute('src');video.load();}
        render();
        try{
            const response=await client.fetchApi('/hutx/minimax-h3/workbench/videos/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...videoIdentity(file),prompt_id:file.promptId})});
            let data;try{data=await response.json();}catch{throw new Error('删除服务不可用，请重启 ComfyUI 后重试。');}
            if(!response.ok)throw new Error(data.error||'视频删除失败，请刷新列表后重试。');
            mediaRevision++;records=records.filter(item=>videoKey(item)!==key);clipDurations.delete(key);openClips.delete(key);
            if(expectedGraph&&readWorkbenchState(expectedGraph).project_id===expectedProject){
                const state=readWorkbenchState(expectedGraph);
                const shots=state.shots.map(shot=>{
                    const results=shot.results.filter(item=>videoKey(item)!==key);
                    return results.length===shot.results.length?shot:{...shot,results,...(!results.length&&shot.state==='complete'?{state:'draft',prompt_id:''}:{} )};
                });
                writeWorkbenchState(expectedGraph,{...state,shortlist:state.shortlist.filter(item=>videoKey(item)!==key),shots});
            }
            if(!destroyed)setStatus('视频已从本机删除，相关片段引用已清理。','success');
        }finally{deletingKey='';if(!destroyed)render();}
    }
    async function assemblyRequest(path,options={}) {
        const response=await client.fetchApi('/hutx/minimax-h3/workbench'+path,options),data=await response.json();
        if(!response.ok){const error=new Error(data.error||'拼接请求失败。');error.status=response.status;throw error;}return data;
    }
    async function startAssembly() {
        if(deletingKey||assemblySubmitting||assembly?.state==='running')throw new Error('视频操作或拼接任务正在运行。');
        const invalid=content.querySelector('.wb-clip input:invalid');if(invalid){invalid.reportValidity();throw new Error('请先修正尚未保存的片段编辑参数。');}
        const active=currentGraph(),current=writeWorkbenchState(active,readWorkbenchState(active)),clips=current.shortlist;
        const total=sequenceDuration(clips,file=>clipDurations.get(videoKey(file)));
        if(total.invalid||total.seconds>600)throw new Error('请检查裁剪范围与累计时长。');
        assemblySubmitting=true;render();
        try{
            const data=await assemblyRequest('/assemble',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clips})});
            if(active!==currentGraph()||readWorkbenchState(active).project_id!==current.project_id)return;
            const state=writeWorkbenchState(active,{...readWorkbenchState(active),assembly_job:data});assembly=state.assembly_job;
            setStatus('正在本机拼接视频…','running');trackAssembly(data.job_id,active,state.project_id);
        }finally{assemblySubmitting=false;if(active===currentGraph())render();}
    }
    function trackAssembly(jobId,active,projectId) {
        clearTimeout(assemblyTimer);assemblyTracking=jobId;const epoch=++assemblyEpoch;
        const poll=async()=>{
            if(destroyed||epoch!==assemblyEpoch)return;
            try{
                const data=await assemblyRequest('/assemble/'+jobId);
                if(destroyed||epoch!==assemblyEpoch)return;
                if(active!==currentGraph()||readWorkbenchState(active).project_id!==projectId){assemblyTracking='';return;}
                const state=writeWorkbenchState(active,{...readWorkbenchState(active),assembly_job:data});assembly=state.assembly_job;
                if(page==='results')render();
                if(data.state==='running')assemblyTimer=setTimeout(poll,1000);
                else if(data.state==='complete')setStatus('拼接成片已保存到 ComfyUI 输出目录。','success');
                else setStatus(data.error||'拼接已停止。',data.state==='error'?'error':'');
            }catch(error){
                if(destroyed||epoch!==assemblyEpoch)return;
                if(active!==currentGraph()||readWorkbenchState(active).project_id!==projectId){assemblyTracking='';return;}
                setStatus(error.message,'error');
                if(error.status===404){writeWorkbenchState(active,{...readWorkbenchState(active),assembly_job:{...assembly,state:'error',error:'拼接任务已过期或服务已重启，请重新拼接。'}});assemblyTracking='';if(page==='results')render();}
                else assemblyTimer=setTimeout(poll,3000);
            }
        };
        assemblyTimer=setTimeout(poll,500);
    }
    async function refreshHistory() {
        if (destroyed || historyBusy) return;
        historyBusy = true; historyError = ''; historyAbort = new AbortController();
        const revision=mediaRevision;
        if (page === 'results') render();
        try {
            const response = await client.fetchApi('/hutx/minimax-h3/workbench/videos', {signal: historyAbort.signal});
            if (!response.ok) throw new Error(response.status===404?'成片管理接口尚未更新，请重启 ComfyUI 后重试。':'无法读取生成历史，请确认 ComfyUI 服务在线。');
            const data = await response.json(); if (destroyed) return;
            if(!Array.isArray(data.videos))throw new Error('成片管理服务尚未更新，请重启 ComfyUI 后重试。');
            if(revision===mediaRevision)records=data.videos.filter(file=>videoIdentity(file)&&typeof file.promptId==='string');historyLoaded = true;
        } catch (error) { if (error.name !== 'AbortError') historyError = error.message || '读取历史失败，请稍后刷新。'; }
        finally { historyBusy = false; historyAbort = null; if (!destroyed && page === 'results') render(); }
    }
    function render() {
        if (destroyed) return;
        pauseVideos(); release(); nodeHost = null; content.replaceChildren();refinementSlot.replaceChildren();refinementSlot.hidden=true;
        const active = currentGraph(), switched = graph !== active||renderedProject!==readWorkbenchState(active).project_id; graph = active;renderedProject=readWorkbenchState(active).project_id;
        if (switched || document.activeElement !== projectName) projectName.value = readWorkbenchState(active).project_name;
        projectName.disabled = !active;
        for (const tab of tabs.children) { const activeTab = tab.dataset.page === page; tab.setAttribute('aria-selected', String(activeTab)); tab.tabIndex = activeTab ? 0 : -1; }
        content.setAttribute('aria-labelledby', `hutx-wb-tab-${page}`);
        const hint=PAGES[page][2],[eyebrow,title]=PAGES[page][3];
        pageEyebrow.textContent=eyebrow;pageTitle.textContent=title;
        pageContext.title=hint;pageContext.setAttribute('aria-label',hint);
        runArea.hidden = page !== 'generate' || !selectedNode('generate'); run.disabled = submitting || sequence.busy;
        run.textContent = submitting ? '正在提交…' : '运行当前画布'; updateProgress();
        if (!active) { empty('请先打开工作流', '工作台会连接您当前打开的 ComfyUI 画布。'); return; }
        if (page === 'roles') renderRoles(); else if (page === 'generate') renderGenerate(); else renderResults();
        signature = graphSignature();updateProgress();
    }
    function graphSignature() { return JSON.stringify([graphNodes(currentGraph()).filter(node => VIDEO_NODE_TYPES.has(node.type) || SPEECH_NODE_TYPES.has(node.type)).map(node => [node.id, node.type, node.title, Boolean(node.hutxWorkbenchPanel)]), selection().roles, selection().generate]); }
    function tick() {
        if (destroyed || !mount) return;
        const visible = mount.isConnected && mount.getClientRects().length > 0;
        if (!visible) { if (expanded) toggleExpanded(false); pauseVideos(); release(); return; }
        updateProgress();
        if (graph !== currentGraph()||renderedProject!==readWorkbenchState(currentGraph()).project_id) { sequence.stopAfterCurrent();assembly=null;assemblyTracking='';assemblyEpoch++;clearTimeout(assemblyTimer);returned = false; render(); return; }
        if (signature !== graphSignature()) { render(); return; }
        if(nodeHost&&(editorNode!==selectedNode(page)||(lease&&lease.panel!==editorNode?.hutxWorkbenchPanel))){returned=false;render();return;}
        if(lease&&nodeHost)lease.reclaim();
        if (!lease && !returned && nodeHost) { nodeHost.replaceChildren(); mountEditor(selectedNode(page)); }
        updateSummary();
    }
    function listen(name, handler) { client.addEventListener(name, handler); listeners.push([name, handler]); }
    for (const name of ['status','execution_start','executing','progress','progress_state','execution_error','execution_interrupted','execution_success']) listen(name,event => {
        executionProgress.handle(name,event.detail);reportExecution();updateProgress();
    });
    listen('executed', event => { if (event.detail?.output?.videos || event.detail?.output?.gifs) scheduleHistory(); });
    function scheduleHistory() { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => { historyLoaded = false; if (page === 'results') refreshHistory(); }, 600); }
    const timer = setInterval(tick, 700);
    return {root, selectPage, refreshHistory, selectedNode, attach(container) { mount = container; container.append(root); returned = false; render();queueSync.start(); }, destroy() {
        if (destroyed) return; destroyed = true;queueSync.stop();sequence.stopAfterCurrent();release(); pauseVideos(); clearInterval(timer); clearTimeout(refreshTimer);clearTimeout(assemblyTimer);historyAbort?.abort();
        for (const [name, handler] of listeners) client.removeEventListener(name, handler); root.remove();
    }};
}

app.registerExtension({name: 'HuTX.Studio.Workbench', setup() {
    const manager = app.extensionManager;
    if (typeof manager?.registerSidebarTab !== 'function') { console.warn('[HuTX] 工作台需要支持侧栏扩展的 ComfyUI 前端。'); return; }
    let view = null;
    manager.registerSidebarTab({id: TAB_ID, icon: 'pi pi-video', title: 'HuTX总台', tooltip: 'HuTX总台 · 角色、镜头与成片', type: 'custom',
        render(container) { view ||= createWorkbench(); view.attach(container); },
        destroy() { view?.destroy(); view = null; },
    });
}});
