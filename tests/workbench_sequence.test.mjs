import test from 'node:test';
import assert from 'node:assert/strict';
import {captureShot,buildShotPrompt,createSequenceRunner,cleanShot} from '../web/js/workbench_sequence.js';
import {readWorkbenchState,writeWorkbenchState} from '../web/js/workbench_state.js';

const prepared=()=>({output:{
    1:{class_type:'GHLocalVideoInputDualEngineGH',inputs:{prompt:'<Picture 1> speaks.',duration_seconds:4,engine_mode:'fused_turbo',main_mode:'all_reference',gh_local_state_json:JSON.stringify({schema_version:1,mode:'all_reference',prompt:'<Picture 1> speaks.',media:[],optimizer:{credential_ref:'never-snapshot'}}),reference_audio_1:['2',0]}},
    2:{class_type:'GHMultiSpeechInputGH',inputs:{role_A:JSON.stringify({enabled:true,text:'你好',adopted_audio_file:'saved',api_key:'never-snapshot'}),role_B:'{}',role_C:'{}'}},
    3:{class_type:'RandomNoise',inputs:{noise_seed:42}},
    4:{class_type:'SamplerCustomAdvanced',inputs:{noise:['3',0],latent_image:['1',2]}},
    5:{class_type:'SaveVideo',inputs:{video:['4',0],filename_prefix:'original'}},
    6:{class_type:'OtherModel',inputs:{api_key:'private-provider'}},
    7:{class_type:'SaveVideo',inputs:{video:['6',0],filename_prefix:'other'}}},workflow:{nodes:[]}});

test('shot snapshots exclude credentials and unrelated output branches',()=>{
    const base=prepared(),shot=captureShot(base,'1','镜头一');
    assert(!JSON.stringify(shot).includes('never-snapshot'));
    const built=buildShotPrompt(base,shot,'run-test');
    assert.deepEqual(Object.keys(built.output),['1','2','3','4','5']);
    assert.match(built.output[5].inputs.filename_prefix,new RegExp(shot.id+'$'));
    assert.equal(base.output[5].inputs.filename_prefix,'original');
    assert.deepEqual(JSON.parse(built.output[2].inputs.role_A),{text:'你好',adopted_audio_file:'saved',enabled:true});
});

test('snapshot retains its prompt, audio and seed after editing live settings',()=>{
    const base=prepared(),shot=captureShot(base,'1','镜头一');
    base.output[1].inputs.prompt='new prompt';base.output[3].inputs.noise_seed=99;
    base.output[2].inputs.role_A=JSON.stringify({text:'新台词',adopted_audio_file:'new'});
    const built=buildShotPrompt(base,shot,'run-test');
    assert.equal(built.output[1].inputs.prompt,'<Picture 1> speaks.');
    assert.equal(built.output[3].inputs.noise_seed,42);
    assert.equal(JSON.parse(built.output[2].inputs.role_A).adopted_audio_file,'saved');
    const changed=prepared();changed.output[4].inputs.latent_image=['3',0];
    assert.throws(()=>buildShotPrompt(changed,shot,'run-test'),/接线已改变/);
});

test('legacy metadata migrates and shot edits remain serializable',()=>{
    const graph={extra:{hutx_workbench:{schema_version:1,project_name:'旧项目',shortlist:[]}},change(){}};
    const old=readWorkbenchState(graph);assert.equal(old.project_name,'旧项目');
    const shot=captureShot(prepared(),'1','镜头一');
    const saved=writeWorkbenchState(graph,{...old,shots:[shot]});
    assert(saved.project_id);assert.equal(saved.schema_version,3);
    assert.equal(readWorkbenchState({extra:JSON.parse(JSON.stringify(graph.extra))}).shots[0].id,shot.id);
});

test('sequence submits one job at a time and takes only its designated output',async()=>{
    const base=prepared(),one=captureShot(base,'1','一'),two=captureShot(base,'1','二');
    const updates=[],queued=[];let waiting=false,polls=0;
    const api={async queuePrompt(_,payload){assert(!waiting);waiting=true;queued.push(payload);return {prompt_id:'job'+queued.length};},async fetchApi(path){
        polls++;const id=path.split('/').at(-1);
        if(polls%2)return {ok:true,json:async()=>({})};
        waiting=false;return {ok:true,json:async()=>({[id]:{status:{completed:true,status_str:'success'},outputs:{5:{videos:[{filename:id+'.mp4',type:'output'}]},99:{videos:[{filename:'wrong-job.mp4'}]}}}})};
    }};
    const runner=createSequenceRunner({api,getPrepared:async()=>base,getGraph:()=>({}),isCurrent:()=>true,sleep:async()=>{},onUpdate:(id,patch)=>updates.push({id,...patch})});
    await runner.start([one,two]);
    assert.equal(queued.length,2);assert(!runner.busy);
    assert.deepEqual(updates.filter(update=>update.state==='complete').map(update=>update.results[0].filename),['job1.mp4','job2.mp4']);
});

test('stop-after-current does not interrupt or submit another job',async()=>{
    const base=prepared(),shots=[captureShot(base,'1','一'),captureShot(base,'1','二')];let count=0,runner;
    const api={async queuePrompt(){count++;return {prompt_id:'known'};},async fetchApi(){return {ok:true,json:async()=>({known:{status:{completed:true},outputs:{5:{videos:[{filename:'done.mp4'}]}}}})};}};
    runner=createSequenceRunner({api,getPrepared:async()=>base,getGraph:()=>({}),isCurrent:()=>true,onUpdate:(_,patch)=>{if(patch.state==='queued')runner.stopAfterCurrent();}});
    await runner.start(shots);assert.equal(count,1);
});

test('resuming an uncertain known task checks history without submitting again',async()=>{
    const base=prepared(),shot={...captureShot(base,'1','一'),state:'unknown',prompt_id:'known'};
    const api={async queuePrompt(){throw Error('duplicate submission');},async fetchApi(){return {ok:true,json:async()=>({known:{status:{completed:true},outputs:{5:{videos:[{filename:'done.mp4'}]}}}})};}};
    const updates=[],runner=createSequenceRunner({api,getPrepared:async()=>base,getGraph:()=>({}),isCurrent:()=>true,onUpdate:(_,patch)=>updates.push(patch)});
    await runner.start([shot]);assert.equal(updates.at(-1).state,'complete');
});

test('network loss retains an unknown job id and stops the remaining shots',async()=>{
    const base=prepared(),shots=[captureShot(base,'1','一'),captureShot(base,'1','二')],updates=[];let count=0;
    const api={async queuePrompt(){count++;return {prompt_id:'known'};},async fetchApi(){throw Error('network lost');}};
    const runner=createSequenceRunner({api,getPrepared:async()=>base,getGraph:()=>({}),isCurrent:()=>true,onUpdate:(_,patch)=>updates.push(patch)});
    await assert.rejects(runner.start(shots),/network lost/);
    assert.equal(count,1);assert.equal(updates.at(-1).state,'unknown');assert.equal(updates.at(-1).prompt_id,'known');
    assert(!runner.busy);
});

test('unadopted saved speech rejects before any job submission',async()=>{
    const base=prepared(),shot=captureShot(base,'1','一');
    shot.speech_inputs[2].inputs.role_A=JSON.stringify({text:'new'});
    const api={async queuePrompt(){throw Error('must not queue');}};
    const runner=createSequenceRunner({api,getPrepared:async()=>base,getGraph:()=>({}),isCurrent:()=>true});
    await assert.rejects(runner.start([shot]),/尚未采用/);
    assert.equal(cleanShot(shot).state,'draft');
});

test('unknown submissions without an id stay blocked across repeated retries',async()=>{
    const base=prepared();let shot={...captureShot(base,'1','一'),state:'unknown',prompt_id:''};let queued=0;
    const runner=createSequenceRunner({api:{async queuePrompt(){queued++;}},getPrepared:async()=>base,getGraph:()=>({}),isCurrent:()=>true,onUpdate:(_,patch)=>{shot={...shot,...patch};}});
    await assert.rejects(runner.start([shot]),/提交结果未知/);
    await assert.rejects(runner.start([shot]),/提交结果未知/);
    assert.equal(queued,0);assert.equal(shot.state,'unknown');
});

test('switching project while a shot finishes prevents subsequent submission',async()=>{
    const base=prepared(),shots=[captureShot(base,'1','一'),captureShot(base,'1','二')];let current=true,count=0;
    const api={async queuePrompt(){count++;return {prompt_id:'one'};},async fetchApi(){return {ok:true,json:async()=>({one:{status:{completed:true},outputs:{5:{videos:[{filename:'one.mp4'}]}}}})};}};
    const runner=createSequenceRunner({api,getPrepared:async()=>base,getGraph:()=>({}),isCurrent:()=>current,onUpdate:(_,patch)=>{if(patch.state==='complete')current=false;}});
    await runner.start(shots);assert.equal(count,1);
});
