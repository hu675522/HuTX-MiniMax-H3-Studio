import {widgetValue} from './workbench_state.js';

const LITEGRAPH = () => globalThis.LiteGraph || globalThis.comfyAPI?.litegraph?.LiteGraph;
export function createWorkbenchNode(graph, type, title) {
    const node = LITEGRAPH()?.createNode(type);
    if (!node) throw new Error(`缺少节点 ${type}，请确认插件和 ComfyUI 已完整加载。`);
    const right = Math.max(0, ...(graph._nodes || []).map(item => item.pos[0] + (item.size?.[0] || 400)));
    node.pos = [right + 80, 80];
    if (title) node.title = title;
    graph.add(node); graph.change?.();
    return node;
}

const setValue = (node, name, value) => {
    const widget = node.widgets?.find(item => item.name === name);
    if (widget) { widget.value = value; widget.callback?.(value); }
};
const connect = (source, name, target, input) => {
    const output = typeof name === 'number' ? name : source.outputs?.findIndex(item => item.name === name);
    const slot = target.inputs?.findIndex(item => item.name === input);
    if (output == null || output < 0 || slot == null || slot < 0 || !source.connect(output, target, slot)) throw new Error(`接口不兼容：${source.type} → ${target.type}.${input}`);
};

export function addStarterPipeline(graph, existing = null) {
    const types = ['BasicGuider', 'RandomNoise', 'SamplerCustomAdvanced', 'MiniMaxH3AVDecodeT8GH', 'CreateVideo', 'SaveVideo'];
    if (!existing) types.unshift('GHLocalVideoInputDualEngineGH');
    const litegraph = LITEGRAPH();
    for (const type of types) if (!litegraph?.registered_node_types?.[type]) throw new Error(`当前宿主缺少 ${type}，无法添加基础线路。`);
    if (existing && existing.type !== 'GHLocalVideoInputDualEngineGH') throw new Error('基础单采线路需要双引擎节点；旧版 Local 节点请使用已有工作流。');
    const added = [];
    const make = type => { const node = createWorkbenchNode(graph, type); added.push(node); return node; };
    try {
        const source = existing || make('GHLocalVideoInputDualEngineGH');
        const guider = make('BasicGuider'), noise = make('RandomNoise'), sampler = make('SamplerCustomAdvanced');
        const decode = make('MiniMaxH3AVDecodeT8GH'), video = make('CreateVideo'), save = make('SaveVideo');
        const x = source.pos[0], y = source.pos[1];
        guider.pos = [x + 720, y]; noise.pos = [x + 720, y + 210]; sampler.pos = [x + 1060, y];
        decode.pos = [x + 1420, y]; video.pos = [x + 1760, y]; save.pos = [x + 2100, y];
        connect(source, 'model', guider, 'model'); connect(source, 'positive', guider, 'conditioning');
        connect(noise, 0, sampler, 'noise'); connect(guider, 0, sampler, 'guider');
        for (const name of ['sampler', 'sigmas']) connect(source, name, sampler, name);
        connect(source, 'av_latent', sampler, 'latent_image'); connect(sampler, 0, decode, 'av_latent');
        for (const name of ['video_vae', 'audio_vae']) connect(source, name, decode, name);
        connect(decode, 'frames', video, 'images');
        const driver = source.inputs?.find(input => input.name === 'driver_audio');
        if (driver?.link != null) connect(source, 'driver_audio_passthrough', video, 'audio');
        else connect(decode, 'generated_audio', video, 'audio');
        connect(video, 0, save, 'video');
        setValue(video, 'fps', 24); setValue(save, 'filename_prefix', 'video/HuTX_Workbench');
        setValue(noise, 'noise_seed', Math.floor(Math.random() * 0x100000000));
        save.title = 'HuTX 工作台 · 保存视频';
        graph.change?.();
        return source;
    } catch (error) { for (const node of added.reverse()) graph.remove(node); throw error; }
}

export function engineLabel(node) {
    return widgetValue(node, 'engine_mode') === 'hyperflow' ? 'HyperFlow · 8 步' : node?.type === 'GHLocalVideoInputDualEngineGH' ? `Fused Turbo · ${widgetValue(node, 'fused_steps') || 4} 步` : 'Local · 原工作流';
}
