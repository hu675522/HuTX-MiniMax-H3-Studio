import fs from 'node:fs';
import assert from 'node:assert/strict';

const source=fs.readFileSync('web/js/dual_engine_input_links.js','utf8');
const links=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

function fixture(names){
    const graph={links:new Map(),nodes:new Map(),next:1,getNodeById(id){return this.nodes.get(id)},removeLink(id){
        const link=this.links.get(id);if(link){const target=this.nodes.get(link.target_id),input=target?.inputs?.[link.target_slot];if(input?.link===id)input.link=null;this.links.delete(id);}
    }};
    const origin={id:1,connect(originSlot,target,targetSlot){
        const current=target.inputs[targetSlot].link;if(current!=null)graph.removeLink(current);
        const id=graph.next++,link={id,origin_id:this.id,origin_slot:originSlot,target_id:target.id,target_slot:targetSlot,type:target.inputs[targetSlot].type};
        graph.links.set(id,link);target.inputs[targetSlot].link=id;return link;
    }};
    const target={id:2,graph,inputs:names.map(name=>({name,type:name.includes('latent')?'LATENT':name.includes('frames')?'IMAGE':'AUDIO',link:null}))};
    graph.nodes.set(1,origin);graph.nodes.set(2,target);return {graph,origin,target};
}
const connect=(fx,name,slot)=>fx.origin.connect(slot,fx.target,fx.target.inputs.findIndex(input=>input.name===name));
const rebuild=(fx,names)=>{for(const input of fx.target.inputs)if(input.link!=null)fx.graph.removeLink(input.link);fx.target.inputs=names.map(name=>({name,type:name.includes('latent')?'LATENT':name.includes('frames')?'IMAGE':'AUDIO',link:null}));};
const originFor=(fx,name)=>{const input=fx.target.inputs.find(item=>item.name===name);return input.link==null?null:fx.graph.links.get(input.link)?.origin_slot};

// Engine switching with mixed sockets and a deliberately changed order.
const all=['driver_audio','reference_audio_1','reference_audio_2','reference_audio_3','continuation_latent','continuation_frames','continuation_audio'];
const fx=fixture(all);connect(fx,'driver_audio',0);connect(fx,'reference_audio_1',1);connect(fx,'reference_audio_2',2);connect(fx,'continuation_latent',3);connect(fx,'continuation_frames',4);connect(fx,'continuation_audio',5);
for(const order of [[...all].reverse(),['reference_audio_3','driver_audio','continuation_audio','reference_audio_1','continuation_latent','reference_audio_2','continuation_frames'],all]){
    const snapshot=links.captureInputConnectionsByName(fx.target,fx.graph);rebuild(fx,order);
    const result=links.restoreInputConnectionsByName(fx.target,snapshot,fx.graph);assert.equal(result.pending.size,0);
    assert.equal(originFor(fx,'driver_audio'),0);assert.equal(originFor(fx,'reference_audio_1'),1);assert.equal(originFor(fx,'reference_audio_2'),2);
    assert.equal(originFor(fx,'continuation_latent'),3);assert.equal(originFor(fx,'continuation_frames'),4);assert.equal(originFor(fx,'continuation_audio'),5);
    assert.equal(fx.graph.links.size,6);
}

// Workflow configure can capture link ids before graph.links is populated.
const reload=fixture(['reference_audio_1','driver_audio']);
const pending=links.captureConfiguredInputConnectionsByName({inputs:[{name:'driver_audio',type:'AUDIO',link:91}]},reload.graph);
reload.graph.links.set(91,{id:91,origin_id:1,origin_slot:7,target_id:2,target_slot:0,type:'AUDIO'});
reload.target.inputs=[{name:'reference_audio_1',type:'AUDIO',link:91},{name:'driver_audio',type:'AUDIO',link:null}];
links.restoreInputConnectionsByName(reload.target,pending,reload.graph);
assert.equal(originFor(reload,'driver_audio'),7);assert.equal(reload.target.inputs[0].link,null);assert.equal(reload.graph.links.size,1);

// Unconnected and deliberately disconnected sockets never revive.
const disconnected=fixture(all);connect(disconnected,'driver_audio',0);disconnected.graph.removeLink(disconnected.target.inputs[0].link);
const empty=links.captureInputConnectionsByName(disconnected.target,disconnected.graph);rebuild(disconnected,[...all].reverse());
links.restoreInputConnectionsByName(disconnected.target,empty,disconnected.graph);
assert.equal(originFor(disconnected,'driver_audio'),null);assert.equal(disconnected.graph.links.size,0);
assert.deepEqual(links.missingStableInputs(disconnected.target),[]);

console.log(JSON.stringify({reload_driver_link:reload.target.inputs.find(input=>input.name==='driver_audio').link,
    engine_switch_links:fx.graph.links.size,protected:all}));
