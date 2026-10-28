import test from 'node:test';
import assert from 'node:assert/strict';
import {DEFAULT_EDIT,cleanClipEdit,clipSpan,sequenceDuration,timeLabel} from '../web/js/workbench_edit.js';
import {readWorkbenchState,writeWorkbenchState} from '../web/js/workbench_state.js';

test('old project clips migrate to non-destructive defaults; edits survive workflow save',()=>{
    for(const schema_version of [1,2]){
        const graph={extra:{hutx_workbench:{schema_version,shortlist:[{filename:'old.mp4',type:'output'}]}}};
        const state=readWorkbenchState(graph);assert.equal(state.schema_version,3);assert.deepEqual(state.shortlist[0].edit,DEFAULT_EDIT);
        state.shortlist[0].edit={trim_start:1,trim_end:3.25,volume:.3,muted:true};
        writeWorkbenchState(graph,state);
        assert.deepEqual(readWorkbenchState(JSON.parse(JSON.stringify(graph))).shortlist[0].edit,state.shortlist[0].edit);
    }
});

test('edits reject malformed ranges and gains instead of silently applying another range',()=>{
    for(const edit of [[],false,{trim_start:-1},{trim_start:120},{trim_end:0},{trim_start:1,trim_end:1.01},{volume:NaN},{volume:Infinity},{volume:2.1},{volume:-.01},{muted:1},{trim_start:true},{trim_end:'3'},{arbitrary:'value'}])assert.throws(()=>cleanClipEdit(edit));
    assert.throws(()=>clipSpan({trim_start:2},1),/超出/);
    assert.throws(()=>clipSpan({trim_end:1.5},1),/超出/);
    const graph={extra:{}};
    assert.throws(()=>writeWorkbenchState(graph,{shortlist:[{filename:'a.mp4',edit:{volume:9}}]}));assert.equal(graph.extra.hutx_workbench,undefined);
});

test('duration totals use exported 24fps spans and flag missing or invalid sources',()=>{
    assert.equal(clipSpan({trim_start:.1,trim_end:.2},1),3/24);
    assert.equal(clipSpan({},NaN),null);
    const clips=[{edit:{trim_start:1,trim_end:3},duration:5},{edit:{trim_end:.1},duration:1},{duration:null},{edit:{trim_end:4},duration:2}];
    assert.deepEqual(sequenceDuration(clips,clip=>clip.duration),{seconds:2+3/24,unknown:1,invalid:1});
    assert.equal(timeLabel(65.25),'1:05.25');
});
