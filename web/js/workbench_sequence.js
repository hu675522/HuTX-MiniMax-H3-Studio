// Shot snapshots and sequential execution. Queues immutable prompts; never edits the live canvas.
import {VIDEO_NODE_TYPES, videoIdentity} from './workbench_state.js';

const SOURCE_FIELDS = new Set(('engine_mode fused_model_name hyperflow_base_model hyperflow_weights hyperflow_strength strict_architecture model_name clip_name video_vae_name audio_vae_name aspect megapixels duration_seconds chunk_ffn_enabled chunk_count chunk_threshold sla_enabled sla_sparsity sla_block_size sla_min_seq_len fused_steps shift_video shift_audio main_mode prompt gh_local_state_json driver_model_family driver_conflict driver_slot first_frame last_frame hybrid_audio ' + Array.from({length:9},(_,i)=>`ref_image_${i+1}`).join(' ') + ' ref_video_1 ref_video_2 ref_video_3 ref_audio_1 ref_audio_2 ref_audio_3').split(' '));
const SPEECH_FIELDS = new Set('engine mode text reference_text reference_file voice speed mock_demo revision cloud_model workspace adopted_audio_file name enabled collapsed reference_name'.split(' '));
export const SAVE_TYPES = new Set(['SaveVideo', 'VHS_VideoCombine', 'SaveWEBM']);
const isLink = value => Array.isArray(value) && value.length === 2 && ['string','number'].includes(typeof value[0]) && Number.isInteger(value[1]);
const clone = value => JSON.parse(JSON.stringify(value));
export const newShotId = () => crypto.randomUUID();

function cleanScalarMap(raw, fields) {
    const result = {};
    for (const [name, value] of Object.entries(raw || {})) if (fields.has(name) && (typeof value === 'string' || typeof value === 'boolean' || typeof value === 'number' && Number.isFinite(value))) {
        if (typeof value === 'string' && value.length > 1048576) throw new Error('镜头参数过大，请减少文本与素材记录。');
        result[name] = value;
    }
    return result;
}
function cleanSource(raw) {
    const result = cleanScalarMap(raw, SOURCE_FIELDS);
    if (result.gh_local_state_json) {
        const state = JSON.parse(result.gh_local_state_json);
        if(!Array.isArray(state.media||[]))throw new Error('镜头素材记录无效。');
        const media=(state.media||[]).map(item=>{
            if(!Array.isArray(item)||item.length!==2||!SOURCE_FIELDS.has(item[0])||typeof item[1]?.name!=='string')throw new Error('镜头素材记录无效。');
            return [item[0],cleanScalarMap(item[1],new Set(['name','kind','muted','trimStart','trimEnd']))];
        });
        result.gh_local_state_json = JSON.stringify({schema_version:1,mode:state.mode,prompt:state.prompt,media});
    }
    return result;
}
function cleanSpeech(raw, type) {
    if (type === 'GHSpeechInputGH') return cleanScalarMap(raw, SPEECH_FIELDS);
    const result = {};
    for (const letter of 'ABC') if (typeof raw?.['role_'+letter] === 'string') result['role_'+letter] = JSON.stringify(cleanScalarMap(JSON.parse(raw['role_'+letter]), SPEECH_FIELDS));
    return result;
}
export function cleanShot(raw) {
    if (!raw || typeof raw !== 'object' || !/^[a-z0-9-]{16,64}$/.test(raw.id) || !VIDEO_NODE_TYPES.has(raw.source_type)) throw new Error('镜头记录无效。');
    const source = cleanSource(raw.source_inputs);
    if (typeof source.prompt !== 'string' || !source.prompt.trim() || !Number.isFinite(source.duration_seconds) || source.duration_seconds < 2 || source.duration_seconds > 30) throw new Error('镜头需要提示词和 2 至 30 秒时长。');
    const speech = {};
    for (const [id, node] of Object.entries(raw.speech_inputs || {})) {
        if (!['GHSpeechInputGH','GHMultiSpeechInputGH'].includes(node?.class_type)) throw new Error('不支持的口播快照。');
        speech[id] = {class_type:node.class_type, inputs:cleanSpeech(node.inputs,node.class_type)};
    }
    const controls = {};
    for (const [id, entry] of Object.entries(raw.controls || {})) {
        if (!['RandomNoise','KSampler','KSamplerAdvanced','ComfySwitchNode'].includes(entry?.class_type)) continue;
        controls[id] = {class_type:entry.class_type,inputs:cleanScalarMap(entry.inputs,new Set(['noise_seed','seed','switch']))};
    }
    const results = (Array.isArray(raw.results) ? raw.results : []).map(videoIdentity).filter(Boolean).slice(0,4);
    return {id:raw.id,title:typeof raw.title === 'string' ? raw.title.slice(0,120) : '未命名镜头',
        source_id:String(raw.source_id),source_type:raw.source_type,output_id:String(raw.output_id),
        source_inputs:source,speech_inputs:speech,controls,topology:typeof raw.topology === 'string' ? raw.topology.slice(0,262144) : '',
        state:['draft','queued','running','complete','error','unknown'].includes(raw.state) ? raw.state : 'draft',
        prompt_id:typeof raw.prompt_id === 'string' ? raw.prompt_id.slice(0,100) : '',
        error:typeof raw.error === 'string' ? raw.error.slice(0,300) : '',results};
}

export function promptSubset(prompt, sinkId) {
    const result = {}, visit = id => {
        id = String(id);
        if (result[id]) return;
        const node = prompt?.[id]; if (!node) throw new Error('镜头接线已失效，请重新保存镜头。');
        result[id] = clone(node);
        for (const value of Object.values(node.inputs || {})) if (isLink(value)) visit(value[0]);
    };
    visit(sinkId); return result;
}
function topology(prompt) {
    return JSON.stringify(Object.entries(prompt).sort(([a],[b])=>a.localeCompare(b)).map(([id,node])=>[id,node.class_type,Object.entries(node.inputs || {}).filter(([,value])=>isLink(value)).sort(([a],[b])=>a.localeCompare(b))]));
}
export function captureShot(prepared, sourceId, title) {
    const prompt = prepared.output, source = prompt?.[String(sourceId)];
    if (!VIDEO_NODE_TYPES.has(source?.class_type)) throw new Error('请选择一个已连接的视频输入节点。');
    const sinks = Object.entries(prompt).filter(([id,node])=>SAVE_TYPES.has(node.class_type) && promptSubset(prompt,id)[String(sourceId)]);
    if (sinks.length !== 1) throw new Error('逐段生成需要该镜头对应一个启用的视频保存节点，请先在画布确认输出线路。');
    const [outputId] = sinks[0], subset = promptSubset(prompt,outputId);
    if (Object.values(subset).filter(node=>VIDEO_NODE_TYPES.has(node.class_type)).length !== 1) throw new Error('该保存线路混用了多个视频输入，请为镜头保留独立的保存线路。');
    const speech = {}, controls = {};
    for (const [id,node] of Object.entries(subset)) {
        if (['GHSpeechInputGH','GHMultiSpeechInputGH'].includes(node.class_type)) speech[id] = {class_type:node.class_type,inputs:cleanSpeech(node.inputs,node.class_type)};
        if (['RandomNoise','KSampler','KSamplerAdvanced','ComfySwitchNode'].includes(node.class_type)) controls[id] = {class_type:node.class_type,inputs:cleanScalarMap(node.inputs,new Set(['noise_seed','seed','switch']))};
    }
    return cleanShot({id:newShotId(),title,source_id:sourceId,source_type:source.class_type,output_id:outputId,
        source_inputs:source.inputs,speech_inputs:speech,controls,topology:topology(subset),state:'draft'});
}

export function buildShotPrompt(prepared, raw, runId) {
    const shot = cleanShot(raw), prompt = promptSubset(prepared.output,shot.output_id);
    if (topology(prompt) !== shot.topology || prompt[shot.source_id]?.class_type !== shot.source_type) throw new Error(`「${shot.title}」的接线已改变，请重新保存该镜头。`);
    Object.assign(prompt[shot.source_id].inputs,shot.source_inputs);
    const patches = {[shot.source_id]:shot.source_inputs};
    for (const [id,node] of Object.entries({...shot.speech_inputs,...shot.controls})) {
        if (prompt[id]?.class_type !== node.class_type) throw new Error('镜头的上游节点已改变，请重新保存。');
        Object.assign(prompt[id].inputs,node.inputs); patches[id] = node.inputs;
    }
    validateAdoptedAudio(prompt);
    const filename = `video/HuTX_Workbench/${runId}/${shot.id}`;
    prompt[shot.output_id].inputs.filename_prefix = filename;
    patches[shot.output_id] = {filename_prefix:filename};
    return {output:prompt,patches};
}
function validateAdoptedAudio(prompt) {
    for (const node of Object.values(prompt)) {
        if (node.class_type === 'GHSpeechInputGH' && !node.inputs.adopted_audio_file) throw new Error('镜头中的口播尚未采用，请先采用后重新保存镜头。');
        if (node.class_type === 'GHMultiSpeechInputGH') for (const letter of 'ABC') {
            const role = JSON.parse(node.inputs['role_'+letter] || '{}');
            if (role.enabled !== false && role.text?.trim() && !role.adopted_audio_file) throw new Error('镜头中的角色尚未采用音频，请先采用后重新保存镜头。');
        }
    }
}

export function shotWorkflow(workflow, graph, patches) {
    const result = clone(workflow);
    if (!Array.isArray(result?.nodes)) return undefined;
    for (const [id,values] of Object.entries(patches)) {
        const serialized = result.nodes.find(node=>String(node.id) === id), live = graph?._nodes?.find(node=>String(node.id) === id);
        if (!serialized || !live || !Array.isArray(serialized.widgets_values)) return undefined;
        const widgets = (live.widgets || []).filter(widget=>widget.options?.serialize !== false && widget.serialize !== false);
        if (widgets.length !== serialized.widgets_values.length) return undefined;
        for (let index=0; index<widgets.length; index++) if (Object.hasOwn(values,widgets[index].name)) serialized.widgets_values[index] = values[widgets[index].name];
        if (values.gh_local_state_json) { serialized.properties ||= {}; serialized.properties.gh_local_video_state = values.gh_local_state_json; }
    }
    // Avoid recursively embedding all shot snapshots in every generated file.
    if (result.extra) delete result.extra.hutx_workbench;
    return result;
}

const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
export function createSequenceRunner({api,getPrepared,getGraph,isCurrent,onUpdate=()=>{},onState=()=>{},sleep=delay,pollMs=1500,maxWaitMs=7200000}) {
    let busy = false, stop = false;
    async function history(promptId) {
        const response = await api.fetchApi('/history/'+encodeURIComponent(promptId));
        if (!response.ok) throw new Error('暂时无法确认任务状态，请保留任务编号并稍后检查。');
        return (await response.json())[promptId];
    }
    async function waitForShot(shot, promptId) {
        const deadline = Date.now()+maxWaitMs;
        while (Date.now()<deadline) {
            const record = await history(promptId);
            if (record) {
                if (record.status?.status_str === 'error') throw new Error('镜头执行失败，请查看 ComfyUI 错误报告。');
                if (record.status?.completed || record.status?.status_str === 'success') {
                    const output = record.outputs?.[shot.output_id];
                    const files = ['videos','gifs','images'].flatMap(key=>Array.isArray(output?.[key]) ? output[key] : []).map(videoIdentity).filter(Boolean);
                    if (!files.length) throw new Error('该镜头任务已结束，但指定保存节点没有返回视频。');
                    return files;
                }
            }
            await sleep(pollMs);
        }
        throw new Error('任务仍未完成，已暂停后续镜头；稍后可检查并继续同一任务。');
    }
    return {get busy(){return busy;},stopAfterCurrent(){if(!busy)return;stop=true;onState('stopping');},async start(rawShots) {
        if (busy) throw new Error('逐段生成已在运行。');
        const shots = rawShots.map(cleanShot).filter(shot=>shot.state!=='complete');
        if (!shots.length) throw new Error('没有待生成镜头。');
        busy=true;stop=false;onState('preparing');
        try {
            const graph = getGraph(), prepared = await getPrepared();
            if (!isCurrent()) throw new Error('项目已切换，本次批量提交已停止。');
            const runId = newShotId();
            const plans = shots.map(shot=>({shot,...buildShotPrompt(prepared,shot,runId)}));
            for (const {shot,output,patches} of plans) {
                if (stop || !isCurrent()) break;
                let promptId = ['queued','running','unknown'].includes(shot.state) ? shot.prompt_id : '';
                let accepted = Boolean(promptId), terminal = false, attempted = false;
                try {
                    if (shot.state === 'unknown' && !promptId) throw new Error('上次提交结果未知，请先检查 ComfyUI 队列与历史；确认后用当前设置重新保存镜头。');
                    if (!promptId) {
                        attempted=true;
                        const queued = await api.queuePrompt(0,{output,workflow:shotWorkflow(prepared.workflow,graph,patches)});
                        if (!queued?.prompt_id) throw new Error('ComfyUI 未返回任务编号，已停止后续提交。');
                        promptId=queued.prompt_id;accepted=true;
                        onUpdate(shot.id,{state:'queued',prompt_id:promptId,error:'',results:[]});
                    }
                    onState('running',shot);
                    const results = await waitForShot(shot,promptId);terminal=true;
                    onUpdate(shot.id,{state:'complete',prompt_id:promptId,error:'',results});
                } catch (error) {
                    // A lost connection may leave the exact job running. Retain its id;
                    // resuming must inspect it instead of submitting a duplicate.
                    if (accepted && !terminal) {
                        try {const record=await history(promptId);terminal=Boolean(record?.status?.completed || record?.status?.status_str==='error' || record?.status?.status_str==='success');} catch {}
                    }
                    const rejected = Number.isInteger(error.status)&&error.status>=400&&error.status<500;
                    const uncertain = shot.state==='unknown'&&!promptId || accepted&&!terminal || attempted&&!promptId&&!rejected;
                    onUpdate(shot.id,{state:uncertain?'unknown':'error',prompt_id:promptId,error:error.message});
                    throw error;
                }
            }
            onState(stop?'stopped':'idle');
        } finally {busy=false;onState('settled');}
    }};
}
