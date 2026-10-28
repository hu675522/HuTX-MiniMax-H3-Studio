import fs from 'node:fs';
import vm from 'node:vm';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(new URL('../web/js/prompt_optimizer_shared.js', import.meta.url), 'utf8').replace(/\bexport /g, '');
class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; }
    append(...items) { this.children.push(...items); }
    setAttribute(key, value) { this.attributes[key] = value; }
}
let milliseconds = 10000, nextInterval = 0;
const intervals = new Map();
const calls = [], alerts = [];
let configResolve, optimizeResolve;
const context = vm.createContext({
    console, AbortController, Blob, structuredClone, INPUT:input,
    document:{createElement:tag=>new Element(tag)},
    performance:{now:()=>milliseconds},
    setInterval:fn=>{ const id=++nextInterval; intervals.set(id,fn); return id; },
    clearInterval:id=>intervals.delete(id),
    alert:message=>alerts.push(message),
    api:{fetchApi:async (url, options={})=>{
        calls.push({url, body:options.body ? JSON.parse(await options.body.text()) : null});
        if (url.endsWith('/config')) {
            if (input.delayConfig) await new Promise(resolve=>{configResolve=resolve;});
            return {ok:true,text:async()=>JSON.stringify({mode:'api',provider:'dashscope',environment_api_key_providers:['dashscope'],auto_optimize:!!input.automatic})};
        }
        if (url.endsWith('/cancel')) return {ok:true};
        if (!url.endsWith('/optimize')) throw new Error('Unexpected endpoint');
        return await new Promise((resolve,reject)=>{
            optimizeResolve=()=>resolve({ok:input.outcome !== 'failure',status:input.outcome === 'failure'?400:200,
                text:async()=>JSON.stringify(input.outcome === 'failure'?{error:'Mock failure'}:{prompt:'Optimized scene.',report:JSON.stringify({status:'optimized',optimizer_elapsed_seconds:2.5})})});
            options.signal.addEventListener('abort',()=>reject(options.signal.reason));
        });
    }},
});
vm.runInContext(source + `
const app={graph:{},queuePrompt:async()=>{globalThis.queued=true;}};
const node={graph:app.graph,mode:0};
let prompt='Original scene.';
globalThis.ctrl=createPromptOptimizerController({api,app,node,label:(en,zh)=>zh,
    getTask:()=> 't2v',getPrompt:()=>prompt,setPrompt:value=>{prompt=value;},getDuration:()=>5,
    getMedia:()=>new Map(),initialState:{config:{provider:'dashscope',auto_optimize:!!INPUT.automatic}}});
globalThis.app=app;
`, context);
const all = el => [el,...(el.children||[]).flatMap(all)];
const badge = all(context.ctrl.element).find(el=>el.className === 'gh-opt-timing');
const button = all(context.ctrl.element).find(el=>el.className === 'gh-opt-run');
const cancel = all(context.ctrl.element).find(el=>el.className === 'gh-opt-cancel');
const snapshot=()=>({hidden:badge.hidden,text:badge.textContent,state:badge.attributes['data-state'],disabled:button.disabled,intervals:intervals.size,
    visibleBadges:all(context.ctrl.element).filter(el=>el.className === 'gh-opt-timing' && !el.hidden).length,
    legacyStatuses:all(context.ctrl.element).filter(el=>el.className === 'gh-opt-status').length});
const advance=ms=>{milliseconds=10000+ms; for(const fn of intervals.values()) fn();};
const flush=async()=>{for(let i=0;i<30;i++) await new Promise(resolve=>setImmediate(resolve));};
const initial=snapshot();
const running=input.automatic ? context.app.queuePrompt() : button.onclick();
const immediate=snapshot();
const duplicate=await button.onclick();
if (input.delayConfig) { advance(1000); configResolve(); }
await flush();
advance(3700);
const ticking=snapshot();
advance(4260);
if(input.outcome === 'cancel') await cancel.onclick(); else optimizeResolve();
await running;
const finished=snapshot();
advance(9000);
const stopped=snapshot();
const report=JSON.parse(context.ctrl.report());
context.ctrl.destroy();
process.stdout.write(JSON.stringify({initial,immediate,duplicate,ticking,finished,stopped,report,calls,alerts,queued:!!context.queued,intervals:intervals.size}));
