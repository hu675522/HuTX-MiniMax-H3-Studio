// ComfyUI reports per-node steps, not a reliable percentage for the entire graph.
export function createExecutionProgress({now = Date.now} = {}) {
    const idle = () => ({phase:'idle',promptId:'',nodeId:'',value:null,max:null,startedAt:null,endedAt:null,message:'',queueRemaining:null,connectionLost:false,recovered:false});
    let state = idle();
    const finished = new Set();
    const running = () => state.phase === 'running';
    const start = (id,recovered=false) => {state = {...idle(),phase:'running',promptId:id || '',startedAt:now(),queueRemaining:state.queueRemaining,recovered};};
    const accepts = detail => !detail?.prompt_id || !state.promptId || String(detail.prompt_id) === state.promptId;
    const steps = (node, value, max) => {
        state.nodeId = node == null ? state.nodeId : String(node);
        const valid = typeof value === 'number' && Number.isFinite(value) && typeof max === 'number' && Number.isFinite(max) && max > 0;
        state.value = valid ? Math.max(0,Math.min(value,max)) : null; state.max = valid ? max : null;
        state.message = '';
    };
    function handle(name, detail) {
        state.connectionLost = false;
        if (name === 'status') {
            const remaining = detail?.status?.exec_info?.queue_remaining ?? detail?.exec_info?.queue_remaining;
            if (Number.isInteger(remaining) && remaining >= 0) state.queueRemaining = remaining;
            return;
        }
        const id = detail?.prompt_id == null ? '' : String(detail.prompt_id);
        if (name === 'execution_start') {
            if (id && !finished.has(id) && !(running() && state.promptId === id)) start(id);
            return;
        }
        if (id && finished.has(id)) return;
        if (['execution_success','execution_error','execution_interrupted'].includes(name) && id === state.promptId && ['queued','unknown'].includes(state.phase)) state.phase='running';
        // progress_state can restore a running task after this panel was opened/reconnected.
        if (['progress','progress_state'].includes(name) && !running() && id) start(id,true);
        if (!running() || !accepts(detail)) return;
        if (name === 'executing') {
            const node = typeof detail === 'object' ? detail?.display_node ?? detail?.node : detail;
            steps(node ?? '',null,null);
            state.message = node == null ? '正在收尾，等待任务完成…' : '';
        } else if (name === 'progress') {
            steps(detail?.display_node ?? detail?.node,detail?.value,detail?.max);
        } else if (name === 'progress_state') {
            const nodes = detail?.nodes && typeof detail.nodes === 'object' ? Object.values(detail.nodes) : [];
            const active = nodes.filter(node => node?.state === 'running').at(-1);
            if (active) steps(active.display_node_id ?? active.node_id,active.value,active.max);
            else {steps('',null,null); state.message = '节点处理完成，正在继续执行…';}
        } else if (['execution_success','execution_error','execution_interrupted'].includes(name)) {
            if (!id) return; // A terminal event must identify its job.
            state.phase = {execution_success:'complete',execution_error:'error',execution_interrupted:'interrupted'}[name];
            state.message = name === 'execution_error' ? String(detail?.exception_message || '请查看 ComfyUI 错误报告。').slice(0,500) : '';
            state.endedAt = now(); state.value = state.max = null;
            finished.add(id); if (finished.size > 100) finished.delete(finished.values().next().value);
        }
    }
    return {handle,
        connectionLost() {state.connectionLost=true;},
        reconcileQueue(data) {
            if (!Array.isArray(data?.queue_running) || !Array.isArray(data?.queue_pending)) throw new Error('Invalid queue response');
            state.connectionLost=false;state.queueRemaining=data.queue_running.length+data.queue_pending.length;
            const current=data.queue_running.find(entry=>Array.isArray(entry)&&typeof entry[1]==='string');
            if (current) {
                if (finished.has(current[1])) return '';
                if (!running() || state.promptId!==current[1]) start(current[1],true);
                if (!state.nodeId) state.message='后端任务正在执行，等待节点上报进度…';
                return '';
            }
            const pending=data.queue_pending.find(entry=>Array.isArray(entry)&&typeof entry[1]==='string');
            if (state.promptId && !finished.has(state.promptId) && !data.queue_pending.some(entry=>entry?.[1]===state.promptId)) return state.promptId;
            if (pending && !running() && !finished.has(pending[1])) {
                if (state.promptId!==pending[1]) state={...idle(),phase:'queued',promptId:pending[1],startedAt:now(),recovered:true,queueRemaining:state.queueRemaining};
                state.phase='queued';
            } else if (!pending && state.phase==='queued') {
                state.phase='unknown';state.message='队列中未发现任务，请检查 ComfyUI 队列与错误提示。';
            }
            return '';
        },
        reconcileHistory(id,record) {
            if (state.promptId!==id || finished.has(id)) return;
            const messages=Array.isArray(record?.status?.messages)?record.status.messages:[];
            const failure=messages.findLast(item=>['execution_error','execution_interrupted'].includes(item?.[0]));
            if (failure) handle(failure[0],{...failure[1],prompt_id:id});
            else if (record?.status?.status_str==='error') handle('execution_error',{prompt_id:id,exception_message:'后端历史记录显示任务失败，请查看 ComfyUI 日志。'});
            else if (record?.status?.completed || record?.status?.status_str==='success') handle('execution_success',{prompt_id:id});
            else {state.phase='unknown';state.message='任务已离开队列，尚未确认执行结果；正在重新同步。';state.value=state.max=null;}
        },
        submitting() {if (!running()) state = {...idle(),phase:'submitting',startedAt:now()};},
        queued() {if (!running() && state.phase === 'submitting') state.phase = 'queued';},
        rejected(message) {if (!running() && ['submitting','queued'].includes(state.phase)) {state.phase='error';state.message=String(message).slice(0,500);state.endedAt=now();}},
        snapshot() {return {...state,elapsedMs:state.startedAt == null ? 0 : Math.max(0,(state.endedAt ?? now())-state.startedAt)};},
    };
}

// Read-only fallback when WebSocket events were missed (refresh/reconnect/client change).
export function createQueueProgressSync({api,progress,onUpdate=()=>{},isVisible=()=>true,intervalMs=3000,timeoutMs=5000}) {
    let stopped=true,busy=false,timer=null,abort=null;
    async function refresh() {
        if (stopped || busy || !isVisible()) return;
        busy=true;abort=new AbortController();const signal=abort.signal;
        const timeout=setTimeout(()=>abort?.abort(),timeoutMs);
        const before=progress.snapshot();
        try {
            const response=await api.fetchApi('/queue',{cache:'no-store',signal});
            if (!response.ok) throw new Error('Queue unavailable');
            const queue=await response.json();
            if (stopped || signal.aborted || progress.snapshot().promptId!==before.promptId) return;
            const id=progress.reconcileQueue(queue);onUpdate();
            if (id) {
                const history=await api.fetchApi('/history/'+encodeURIComponent(id),{cache:'no-store',signal});
                if (!history.ok) throw new Error('History unavailable');
                const records=await history.json();
                if (stopped || signal.aborted) return;
                progress.reconcileHistory(id,records[id]);onUpdate();
            }
        } catch {
            if (!stopped) {progress.connectionLost();onUpdate();}
        } finally {clearTimeout(timeout);busy=false;abort=null;}
    }
    const tick=async()=>{await refresh();if(!stopped)timer=setTimeout(tick,intervalMs);};
    return {refresh,start(){if(stopped){stopped=false;tick();}},stop(){stopped=true;clearTimeout(timer);abort?.abort();}};
}
