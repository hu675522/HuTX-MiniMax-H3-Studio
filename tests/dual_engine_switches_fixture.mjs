import fs from 'node:fs';
import assert from 'node:assert/strict';

const source=fs.readFileSync('web/js/dual_engine_switches.js','utf8');
const {syncDualEngineSwitches,dualEngineBranchState,setDualEngineBranch,restoreDualEngineSwitches}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

const graph={links:new Map(),_nodes:[],changes:0,getNodeById(id){return this._nodes.find(node=>node.id===id)},change(){this.changes++}};
const dual={id:2,type:'GHLocalVideoInputDualEngineGH',graph,inputs:[]};
const main={id:5,type:'SamplerCustomAdvanced',graph,inputs:[{name:'model',link:1}]};
const decode={id:13,type:'MiniMaxH3AVDecodeT8GH',graph,inputs:[{name:'latent',link:2}]};
const callbacks=[];
function toggle(id,title,link){return {id,type:'ComfySwitchNode',title,graph,
    inputs:[{name:'on_false',link},{name:'on_true',link:null}],
    widgets:[{name:'switch',value:false,callback(value){callbacks.push([id,value])}}]};}
const second=toggle(11,'★ 二采开关 · OFF=主采样 / ON=二采',3);
const face=toggle(18,'★ VOSR2 修脸开关',4);
const other=toggle(25,'★ VOSR2 修脸开关',5);
const unrelated={id:99,type:'SamplerCustomAdvanced',graph,inputs:[]};
graph._nodes.push(dual,main,decode,second,face,other,unrelated);
for(const [id,origin_id,target_id] of [[1,2,5],[2,5,13],[3,5,11],[4,13,18],[5,99,25]])
    graph.links.set(id,{id,origin_id,origin_slot:0,target_id,target_slot:0});
const linksBefore=[...graph.links.keys()];

assert.equal(syncDualEngineSwitches(dual,'fused_turbo'),2);
assert.equal(second.widgets[0].value,true);
assert.equal(face.widgets[0].value,true);
assert.equal(other.widgets[0].value,false);
assert.equal(syncDualEngineSwitches(dual,'hyperflow'),2);
assert.equal(second.widgets[0].value,false);
assert.equal(face.widgets[0].value,false);
assert.equal(syncDualEngineSwitches(dual,'fused_turbo'),2);
assert.equal(syncDualEngineSwitches(dual,'fused_turbo'),0);
assert.equal(graph.changes,3);
assert.equal(callbacks.length,6);
dual.widgets=[{name:'engine_mode',value:'fused_turbo'}];
assert.equal(dualEngineBranchState(dual,'second').available,true);
setDualEngineBranch(dual,'second',false);
assert.equal(second.widgets[0].value,false);assert.equal(face.widgets[0].value,true);
assert.equal(dual.properties.hutx_manual_branch_controls,1);
assert.equal(restoreDualEngineSwitches(dual,'fused_turbo'),0);assert.equal(second.widgets[0].value,false);
dual.widgets[0].value='hyperflow';assert.equal(syncDualEngineSwitches(dual,'hyperflow'),1);
assert.throws(()=>setDualEngineBranch(dual,'face',true),/Fused Turbo/);
dual.widgets[0].value='fused_turbo';assert.equal(syncDualEngineSwitches(dual,'fused_turbo'),2);
const duplicate=toggle(50,'二采开关 · another',3);graph._nodes.push(duplicate);
assert.equal(dualEngineBranchState(dual,'second').available,false);
assert.throws(()=>setDualEngineBranch(dual,'second',false),/多个/);
assert.equal(second.widgets[0].value,true);graph._nodes.pop();
face.mode=4;assert.throws(()=>setDualEngineBranch(dual,'face',false),/旁路/);face.mode=0;
assert.equal(other.widgets[0].value,false);
assert.deepEqual([...graph.links.keys()],linksBefore);
console.log(JSON.stringify({switches:2,transitions:3,unchangedLinks:linksBefore.length}));
