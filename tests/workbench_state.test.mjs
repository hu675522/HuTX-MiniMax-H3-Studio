import test from 'node:test';
import assert from 'node:assert/strict';
import {videoIdentity, historyVideos, readWorkbenchState, writeWorkbenchState, connectRoleAudio, validateGeneration, hasVideoOutput} from '../web/js/workbench_state.js';
import {addStarterPipeline} from '../web/js/workbench_graph.js';

function graphFixture() {
    const graph = {_nodes: [], links: {}, extra: {}, count: 0, getNodeById(id) { return this._nodes.find(node => String(node.id) === String(id)); }, change() {},
        add(node) { node.id = ++this.count; node.graph = this; this._nodes.push(node); }, remove(node) { node.onRemoved?.(); this._nodes.splice(this._nodes.indexOf(node), 1); }};
    function node(type, inputs = [], outputs = ['value']) {
        const result = {type, mode: 0, pos: [0, 0], size: [400, 200], widgets: [], inputs: inputs.map(name => ({name, link: null})), outputs: outputs.map(name => ({name, links: []})),
            connect(index, target, slot) { const id = Object.keys(graph.links).length + 1; const link = {id, origin_id: this.id, origin_slot: index, target_id: target.id, target_slot: slot}; graph.links[id] = link; this.outputs[index].links.push(id); target.inputs[slot].link = id; return link; },
            disconnectInput(slot) { const id = this.inputs[slot].link; const link = graph.links[id]; if (link) graph.getNodeById(link.origin_id).outputs[link.origin_slot].links = graph.getNodeById(link.origin_id).outputs[link.origin_slot].links.filter(value => value !== id); this.inputs[slot].link = null; delete graph.links[id]; }};
        graph.add(result); return result;
    }
    return {graph, node};
}

test('history admits only local video descriptors from HuTX generations', () => {
    const output = {videos: [{filename: 'movie.mp4', subfolder: 'video', type: 'output'}, {filename: '../bad.mp4'}, {filename: 'https://evil.invalid/video.mp4'}, {filename: 'file.mp4', type: 'input'}], images: [{filename: 'frame.png', type: 'output'}]};
    const history = {foreign: {prompt: [0, 'foreign', {1: {class_type: 'OtherModel'}}], outputs: {7: output}}, local: {prompt: [1, 'local', {2: {class_type: 'GHLocalVideoInputDualEngineGH'}}], outputs: {7: output}}};
    assert.deepEqual(historyVideos(history), [{filename: 'movie.mp4', subfolder: 'video', type: 'output', promptId: 'local', nodeId: '7', title: 'movie.mp4'}]);
    assert.equal(videoIdentity({filename: 'C:\\private\\file.mp4'}), null);
});

test('workflow metadata stores bounded references, never credentials or video bytes', () => {
    const graph = {extra: {existing: true}, change() {}};
    const state = writeWorkbenchState(graph, {project_name: '短剧', api_key: 'not-to-be-stored', shortlist: [{filename: 'one.mp4', type: 'output', title: '镜头一', prompt: 'private'}, {filename: 'one.mp4', type: 'output'}, {filename: '../other.mp4'}]});
    assert.equal(graph.extra.existing, true); assert.equal(state.shortlist.length, 1);
    assert.deepEqual(Object.keys(state).sort(), ['assembly_job','project_id','project_name', 'schema_version', 'shortlist','shots']);
    assert(!JSON.stringify(state).includes('private')); assert(!JSON.stringify(state).includes('not-to-be-stored'));
    assert.deepEqual(readWorkbenchState({extra: JSON.parse(JSON.stringify(graph.extra))}), state);
});

test('three-role wiring preflights every slot before changing any existing cable', () => {
    const {graph, node} = graphFixture();
    const roles = node('GHMultiSpeechInputGH', [], ['audio_A', 'audio_B', 'audio_C']);
    const target = node('GHLocalVideoInputDualEngineGH', ['reference_audio_1', 'reference_audio_2', 'reference_audio_3']);
    const other = node('OtherAudio'); other.connect(0, target, 1);
    const before = JSON.stringify(graph.links);
    assert.throws(() => connectRoleAudio(graph, roles, target), /已有其它连接/);
    assert.equal(JSON.stringify(graph.links), before); assert.equal(target.inputs[0].link, null);
    target.disconnectInput(1); assert.equal(connectRoleAudio(graph, roles, target), 3);
    assert.equal(Object.keys(graph.links).length, 3);
    connectRoleAudio(graph, roles, target); assert.equal(Object.keys(graph.links).length, 3);
});

test('partial three-role connection failure rolls back only its new connections', () => {
    const {graph, node} = graphFixture();
    const roles = node('GHMultiSpeechInputGH', [], ['audio_A', 'audio_B', 'audio_C']);
    const target = node('GHLocalVideoInputGH', ['reference_audio_1', 'reference_audio_2', 'reference_audio_3']);
    const connect = roles.connect; roles.connect = function(index, ...args) { return index === 1 ? null : connect.call(this, index, ...args); };
    assert.throws(() => connectRoleAudio(graph, roles, target), /连接失败/);
    assert.deepEqual(graph.links, {});
});

test('generation requires adopted audio and an enabled save path; bypassed refiners remain usable', () => {
    const {graph, node} = graphFixture();
    const source = node('GHLocalVideoInputDualEngineGH', ['reference_audio_1']); source.widgets = [{name: 'prompt', value: '<Picture 1> speaks.'}];
    assert.throws(() => validateGeneration(graph, source), /保存节点/);
    const refine = node('Refiner', ['latent']); refine.mode = 4; source.connect(0, refine, 0);
    const save = node('SaveVideo', ['video']); refine.connect(0, save, 0);
    assert(hasVideoOutput(graph, source)); assert(validateGeneration(graph, source));
    const roles = node('GHMultiSpeechInputGH'); roles.widgets = [{name: 'role_A', value: JSON.stringify({text: '你好'})}]; roles.connect(0, source, 0);
    assert.throws(() => validateGeneration(graph, source), /尚未采用/);
    roles.widgets[0].value = JSON.stringify({text: '你好', adopted_audio_file: 'adopted'}); assert(validateGeneration(graph, source));
    save.mode = 2; assert(!hasVideoOutput(graph, source));
});

test('starter graph refuses missing host nodes before mutating the graph', () => {
    const {graph} = graphFixture();
    globalThis.LiteGraph = {registered_node_types: {}};
    assert.throws(() => addStarterPipeline(graph), /缺少/); assert.equal(graph._nodes.length, 0);
    delete globalThis.LiteGraph;
});
