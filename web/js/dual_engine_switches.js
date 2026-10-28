// Keep the two optional branches in the same workflow aligned with the
// selected dual engine. Never create or reconnect graph links here.
const graphLink=(graph,id)=>id==null?null:(graph?.links instanceof Map?graph.links.get(id):graph?.links?.[id])||null;
const graphNode=(graph,id)=>graph?.getNodeById?.(id)||graph?._nodes_by_id?.[id]||graph?._nodes?.find?.(item=>item.id===id)||null;

function originatesFrom(graph,current,targetId,seen=new Set()){
    if(!current||seen.has(current.id))return false;
    if(current.id===targetId)return true;
    seen.add(current.id);
    return (current.inputs||[]).some(input=>{
        const link=graphLink(graph,input.link);
        return link&&originatesFrom(graph,graphNode(graph,link.origin_id),targetId,seen);
    });
}

function associatedSwitches(source,kind){
    const graph=source?.graph;
    if(!graph)return [];
    const label=kind==='second'?/二采|second.?pass/i:/VOSR2|修脸/i;
    return (graph._nodes||[]).filter(candidate=>{
        if(candidate.type!=='ComfySwitchNode'||!label.test(String(candidate.title||'')))return false;
        const bypass=candidate.inputs?.find(input=>input.name==='on_false');
        const link=graphLink(graph,bypass?.link);
        return Boolean(link&&originatesFrom(graph,graphNode(graph,link.origin_id),source.id));
    });
}

export function dualEngineBranchState(source,kind){
    if(!['second','face'].includes(kind))throw new Error('Unknown refinement branch');
    const matches=associatedSwitches(source,kind);
    const target=matches.length===1?matches[0]:null,widget=target?.widgets?.find(item=>item.name==='switch');
    const reason=matches.length>1?'发现多个对应开关，请在画布中确认线路。':!widget?'未接入对应开关线路。':target.inputs?.some(input=>input.name==='switch'&&input.link!=null)?'开关由外部输入控制，请在画布调整。':target.mode!=null&&target.mode!==0?'画布开关节点已禁用或旁路。':'';
    return {available:!reason,value:Boolean(widget?.value),reason,target,widget};
}

export function setDualEngineBranch(source,kind,enabled){
    if(source?.type!=='GHLocalVideoInputDualEngineGH'||source.widgets?.find(item=>item.name==='engine_mode')?.value!=='fused_turbo')throw new Error('画面精修开关仅在 Fused Turbo 模式下使用。');
    const state=dualEngineBranchState(source,kind);
    if(!state.available)throw new Error(state.reason);
    const previous=state.widget.value;
    try{
        state.widget.value=Boolean(enabled);
        state.widget.callback?.call(state.widget,Boolean(enabled),state.target.graph,state.target);
    }catch(error){state.widget.value=previous;throw error;}
    // The actual switch values serialize normally. Preserve manual choices on reload.
    source.properties||={};source.properties.hutx_manual_branch_controls=1;
    state.target.setDirtyCanvas?.(true,true);source.graph?.change?.();
}

export function restoreDualEngineSwitches(source,mode){
    if(mode==='fused_turbo'&&source?.properties?.hutx_manual_branch_controls===1)return 0;
    return syncDualEngineSwitches(source,mode);
}

/** Returns the number of changed switches; ambiguous matches are left alone. */
export function syncDualEngineSwitches(source,mode){
    if(!source||!['fused_turbo','hyperflow'].includes(mode))return 0;
    const enabled=mode==='fused_turbo';
    let changed=0;
    for(const kind of ['second','face']){
        const matches=associatedSwitches(source,kind);
        if(matches.length!==1)continue;
        const target=matches[0],widget=target.widgets?.find(item=>item.name==='switch');
        if(!widget||widget.value===enabled)continue;
        widget.value=enabled;
        widget.callback?.call(widget,enabled,target.graph,target);
        target.setDirtyCanvas?.(true,true);
        changed++;
    }
    if(changed)source.graph?.change?.();
    return changed;
}
