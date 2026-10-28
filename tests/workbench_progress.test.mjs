import test from 'node:test';
import assert from 'node:assert/strict';
import {createExecutionProgress,createQueueProgressSync} from '../web/js/workbench_progress.js';

test('submission, queue, real steps and post-sampling processing are distinct phases',()=>{
    let clock=100;const tracker=createExecutionProgress({now:()=>clock});
    tracker.submitting();assert.equal(tracker.snapshot().phase,'submitting');
    tracker.queued();assert.equal(tracker.snapshot().phase,'queued');
    tracker.handle('execution_start',{prompt_id:'one'});clock+=1000;
    tracker.handle('executing','14');assert.equal(tracker.snapshot().max,null);
    tracker.handle('progress',{prompt_id:'one',node:'14',value:2,max:4});
    assert.deepEqual([tracker.snapshot().nodeId,tracker.snapshot().value,tracker.snapshot().max],['14',2,4]);
    tracker.handle('progress',{prompt_id:'one',node:'14',value:4,max:4});
    assert.equal(tracker.snapshot().phase,'running');
    tracker.handle('executing','15');assert.equal(tracker.snapshot().value,null);
    tracker.handle('executing',null);assert.equal(tracker.snapshot().phase,'running');
    tracker.handle('execution_success',{prompt_id:'one'});clock+=1000;
    assert.equal(tracker.snapshot().phase,'complete');assert.equal(tracker.snapshot().elapsedMs,1000);
    tracker.handle('progress',{prompt_id:'one',value:1,max:4});assert.equal(tracker.snapshot().phase,'complete');
});

test('late errors/success/progress from another job cannot settle the current task',()=>{
    const tracker=createExecutionProgress();tracker.handle('execution_start',{prompt_id:'active'});
    for(const name of ['progress','progress_state','execution_error','execution_interrupted','execution_success'])tracker.handle(name,{prompt_id:'old',value:2,max:4});
    assert.equal(tracker.snapshot().phase,'running');assert.equal(tracker.snapshot().value,null);
    tracker.handle('execution_success',{});assert.equal(tracker.snapshot().phase,'running');
    tracker.handle('execution_error',{prompt_id:'active',exception_message:'CUDA test error'});
    assert.equal(tracker.snapshot().phase,'error');assert.equal(tracker.snapshot().message,'CUDA test error');
    tracker.handle('execution_start',{prompt_id:'next'});assert.equal(tracker.snapshot().message,'');
    tracker.handle('execution_interrupted',{prompt_id:'next'});assert.equal(tracker.snapshot().phase,'interrupted');
});

test('new progress_state restores active execution, selects running node and avoids stale finished-node counts',()=>{
    const tracker=createExecutionProgress();tracker.handle('progress_state',{prompt_id:'resume',nodes:{
        12:{state:'finished',value:8,max:8,node_id:'12'},14:{state:'running',value:1,max:4,node_id:'14',display_node_id:'subgraph:14'},
    }});
    assert.equal(tracker.snapshot().nodeId,'subgraph:14');assert.equal(tracker.snapshot().value,1);
    tracker.handle('progress_state',{prompt_id:'resume',nodes:{14:{state:'finished',value:4,max:4,node_id:'14'}}});
    assert.equal(tracker.snapshot().phase,'running');assert.equal(tracker.snapshot().max,null);
    tracker.handle('progress_state',{prompt_id:'resume',nodes:{14:{state:'running',value:NaN,max:4,node_id:'14'}}});
    assert.equal(tracker.snapshot().max,null);
    tracker.handle('progress',{prompt_id:'resume',value:50,max:4});assert.equal(tracker.snapshot().value,4);
    tracker.handle('progress',{prompt_id:'resume',value:1,max:0});assert.equal(tracker.snapshot().max,null);
});

test('a second queue submission cannot erase an already running task, or overwrite a fast terminal event',()=>{
    const tracker=createExecutionProgress();tracker.handle('execution_start',{prompt_id:'active'});
    tracker.handle('progress',{prompt_id:'active',node:'1',value:3,max:4});
    tracker.submitting();tracker.queued();tracker.rejected('second submission failed');
    assert.equal(tracker.snapshot().value,3);assert.equal(tracker.snapshot().phase,'running');
    tracker.handle('execution_success',{prompt_id:'active'});tracker.queued();assert.equal(tracker.snapshot().phase,'complete');
    tracker.submitting();tracker.rejected('validation failed');assert.equal(tracker.snapshot().phase,'error');
});

test('queue recovery fixes missed start events and retains genuine sampling steps',()=>{
    const tracker=createExecutionProgress();tracker.submitting();tracker.queued();
    tracker.reconcileQueue({queue_running:[[0,'running-job',{}]],queue_pending:[[1,'later-job',{}]]});
    assert.equal(tracker.snapshot().phase,'running');assert.equal(tracker.snapshot().promptId,'running-job');
    assert.equal(tracker.snapshot().recovered,true);assert.equal(tracker.snapshot().queueRemaining,2);
    tracker.handle('progress',{prompt_id:'running-job',node:'14',value:2,max:4});
    tracker.reconcileQueue({queue_running:[[0,'running-job',{}]],queue_pending:[]});assert.equal(tracker.snapshot().value,2);
    assert.equal(tracker.reconcileQueue({queue_running:[],queue_pending:[]}),'running-job');
    tracker.reconcileHistory('running-job',{status:{status_str:'error',completed:true,messages:[['execution_error',{exception_message:'cuBLAS handle creation error: 1'}]]}});
    assert.equal(tracker.snapshot().phase,'error');assert.match(tracker.snapshot().message,/cuBLAS/);
});

test('queue disappearance is not success, and a later history record resolves unknown state',()=>{
    const tracker=createExecutionProgress();tracker.reconcileQueue({queue_running:[[0,'task',{}]],queue_pending:[]});
    tracker.reconcileHistory('task',undefined);assert.equal(tracker.snapshot().phase,'unknown');
    tracker.reconcileHistory('task',{status:{status_str:'success',completed:true}});assert.equal(tracker.snapshot().phase,'complete');
    tracker.reconcileHistory('other',{status:{status_str:'error'}});assert.equal(tracker.snapshot().phase,'complete');
    tracker.submitting();tracker.reconcileQueue({queue_running:[],queue_pending:[]});assert.equal(tracker.snapshot().phase,'submitting');
    tracker.queued();tracker.reconcileQueue({queue_running:[],queue_pending:[]});assert.equal(tracker.snapshot().phase,'unknown');
});

test('read-only sync recovers backend failure without submitting or interrupting any job',async()=>{
    const tracker=createExecutionProgress(),calls=[];
    const api={async fetchApi(url,options){calls.push([url,options]);return {ok:true,json:async()=>url==='/queue'?{queue_running:[],queue_pending:[]}:{task:{status:{status_str:'error',messages:[['execution_error',{exception_message:'aimdo memory compile error'}]]}}}};}};
    tracker.reconcileQueue({queue_running:[[0,'task',{}]],queue_pending:[]});
    const sync=createQueueProgressSync({api,progress:tracker});
    try {sync.start();await new Promise(resolve=>setTimeout(resolve,0));assert.equal(tracker.snapshot().phase,'error');assert.match(tracker.snapshot().message,/aimdo/);assert.deepEqual(calls.map(call=>call[0]),['/queue','/history/task']);assert(calls.every(call=>!call[1].method));}
    finally {sync.stop();}
});

test('disconnection retains the last known job and reports unavailable state, not completion',async()=>{
    const tracker=createExecutionProgress();tracker.handle('execution_start',{prompt_id:'gpu-busy'});
    const sync=createQueueProgressSync({api:{fetchApi:async()=>{throw Error('offline');}},progress:tracker});
    try {sync.start();await new Promise(resolve=>setTimeout(resolve,0));assert.equal(tracker.snapshot().connectionLost,true);assert.equal(tracker.snapshot().phase,'running');}
    finally {sync.stop();}
    tracker.reconcileQueue({queue_running:[[0,'gpu-busy',{}]],queue_pending:[]});assert.equal(tracker.snapshot().connectionLost,false);
});

test('late REST response cannot overwrite a newly started WebSocket job',async()=>{
    let resolve;const tracker=createExecutionProgress();
    const sync=createQueueProgressSync({api:{fetchApi:()=>new Promise(done=>resolve=done)},progress:tracker});
    try {sync.start();tracker.handle('execution_start',{prompt_id:'new-job'});resolve({ok:true,json:async()=>({queue_running:[[0,'old-job',{}]],queue_pending:[]})});await new Promise(resolve=>setTimeout(resolve,0));assert.equal(tracker.snapshot().promptId,'new-job');}
    finally {sync.stop();}
});
