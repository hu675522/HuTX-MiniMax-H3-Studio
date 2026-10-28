export const DUAL_ENGINE_STABLE_INPUTS=Object.freeze([
    'driver_audio','reference_audio_1','reference_audio_2','reference_audio_3',
    'continuation_latent','continuation_frames','continuation_audio'
]);

const graphLink=(graph,id)=>id==null?null:(graph?.links instanceof Map?graph.links.get(id):graph?.links?.[id])||null;
const graphLinks=graph=>graph?.links instanceof Map?[...graph.links.values()]:Object.values(graph?.links||{});
const graphLinkId=(graph,link)=>link?.id??(graph?.links instanceof Map?[...graph.links].find(([,value])=>value===link)?.[0]:Object.entries(graph?.links||{}).find(([,value])=>value===link)?.[0]);

function savedConnection(input,graph){
    if(!input?.name||input.link==null)return null;
    const link=graphLink(graph,input.link);
    return [input.name,{
        link_id:input.link,
        origin_id:link?.origin_id,
        origin_slot:link?.origin_slot,
        type:link?.type||input.type
    }];
}

/** Capture only links that exist at the exact moment a rebuild starts. */
export function captureInputConnectionsByName(node,graph=node?.graph){
    const saved=new Map();
    for(const input of node?.inputs||[]){
        const entry=savedConnection(input,graph);if(entry)saved.set(...entry);
    }
    return saved;
}

/** Capture serialized link ids during workflow configure, before graph.links exists. */
export function captureConfiguredInputConnectionsByName(info,graph){
    const saved=new Map();
    for(const input of info?.inputs||[]){
        const entry=savedConnection(input,graph);if(entry)saved.set(...entry);
    }
    return saved;
}

export function mergeInputConnectionSnapshots(...snapshots){
    const merged=new Map();
    for(const snapshot of snapshots)for(const [name,value] of snapshot||[])merged.set(name,value);
    return merged;
}

function originNode(graph,id){
    return graph?.getNodeById?.(id)||graph?._nodes_by_id?.[id]||graph?._nodes?.find?.(node=>node.id===id)||null;
}

/**
 * Restore by input name through LiteGraph's connect API.  Never writes
 * input.link directly and never assumes that the input index stayed stable.
 */
export function restoreInputConnectionsByName(node,snapshot,graph=node?.graph,{warn=false}={}){
    const pending=new Map(),restored=[];
    if(!(snapshot instanceof Map)||!snapshot.size)return {pending,restored};
    for(const [name,raw] of snapshot){
        const targetSlot=(node?.inputs||[]).findIndex(input=>input?.name===name);
        if(targetSlot<0){
            pending.set(name,raw);if(warn)console.warn(`[HuTX DualEngine] skipped missing input: ${name}`);continue;
        }
        const current=node.inputs[targetSlot];
        if(current.link!=null&&graphLink(graph,current.link))continue;
        const linked=graphLink(graph,raw.link_id),saved={
            ...raw,
            origin_id:raw.origin_id??linked?.origin_id,
            origin_slot:raw.origin_slot??linked?.origin_slot,
            type:raw.type||linked?.type
        };
        if(saved.origin_id==null||saved.origin_slot==null){pending.set(name,saved);continue;}
        const stale=graphLinks(graph).find(link=>link&&link.origin_id===saved.origin_id&&
            link.origin_slot===saved.origin_slot&&link.target_id===node.id);
        if(stale){
            const id=graphLinkId(graph,stale);if(id!=null&&graph?.removeLink)graph.removeLink(id);
        }
        const origin=originNode(graph,saved.origin_id);
        if(!origin?.connect){pending.set(name,saved);continue;}
        origin.connect(saved.origin_slot,node,targetSlot);
        restored.push(name);
    }
    return {pending,restored};
}

/** Stable sockets are declared by Python and must never be engine-dependent. */
export function missingStableInputs(node){
    const names=new Set((node?.inputs||[]).map(input=>input?.name));
    return DUAL_ENGINE_STABLE_INPUTS.filter(name=>!names.has(name));
}
