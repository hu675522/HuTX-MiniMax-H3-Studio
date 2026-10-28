// Actual shared model selector, with controlled transport and no provider requests.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
class Element {
    constructor(tag){this.tag=tag;this.children=[];this.style={};this.value='';this.listeners={};}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    setAttribute(){}
    addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
}
const context=vm.createContext({document:{createElement:tag=>new Element(tag)},
    Option:class extends Element{constructor(text,value){super('option');this.textContent=text;this.value=value;}},
    AbortController,URLSearchParams,console,setTimeout,clearTimeout,setInterval,clearInterval});
vm.runInContext(fs.readFileSync(new URL('../web/js/prompt_optimizer_shared.js',import.meta.url),'utf8').replace(/\bexport /g,''),context);
const turn=()=>new Promise(resolve=>setTimeout(resolve,0));
const requests=[],resolvers=[];
let fail=false;
const api={fetchApi:async(url,options)=>{
    requests.push({url,options});
    const response=await new Promise(resolve=>resolvers.push(resolve));
    return {ok:!fail,status:fail?401:200,text:async()=>JSON.stringify(response)};
}};
context.fixture={api,provider:{value:'dashscope'},mode:{value:'api'},model:new Element('input'),readMedia:new Element('input')};
context.fixture.model.value='qwen-vl-max';context.fixture.readMedia.checked=true;
const selector=vm.runInContext('createApiModelSelector(fixture)',context);
const [,select,model,status]=selector.root.children;
const [search,refresh]=selector.root.children[0].children;
const pending=selector.refresh();
assert.equal(refresh.disabled,true);
resolvers.shift()({models:[{id:'qwen3-vl-plus',vision:null},{id:'text-model',vision:false},{id:'vision-model',vision:true}]});
await pending;
assert.equal(model.value,'qwen-vl-max');
assert.match(status.textContent,/重新选择/);
await assert.rejects(selector.validate(),/有效模型/);
assert.equal(select.children.find(row=>row.value==='text-model').disabled,true);
select.value='qwen3-vl-plus';select.onchange();await selector.validate();
search.value='vision';search.oninput();
assert.equal(select.children.length,2); // Selected model is retained beside the search match.
assert.equal(model.hidden,true);

// The provider A request finishing after B cannot contaminate B's list or status.
context.fixture.provider.value='openai';const slow=selector.providerChanged();
context.fixture.provider.value='openrouter';const fast=selector.providerChanged();
resolvers[1]({models:[{id:'provider-b',vision:true}]});resolvers.splice(1,1);await fast;
resolvers.shift()({models:[{id:'provider-a',vision:true}]});await slow;
assert.equal(select.children.some(row=>row.value==='provider-a'),false);
assert.equal(select.children.some(row=>row.value==='provider-b'),true);
search.value='';search.oninput();
assert.equal(select.children.some(row=>row.value==='provider-b'),true);
context.fixture.provider.value='dashscope';const back=selector.providerChanged();
resolvers.shift()({models:[{id:'qwen3-vl-plus',vision:null}]});await back;
assert.equal(model.value,'qwen3-vl-plus');await selector.validate();

// Failed refresh preserves manual input and explicitly marks the choice unverified.
fail=true;const bad=refresh.onclick();resolvers.shift()({error:'鉴权失败 (HTTP 401)'});await bad;
assert.equal(model.hidden,false);assert.equal(model.value,'qwen3-vl-plus');assert.match(status.textContent,/未验证/);
await selector.validate();fail=false;
context.fixture.mode.value='local';await selector.refresh();
const count=requests.length;context.fixture.mode.value='api';context.fixture.provider.value='custom';await selector.providerChanged();
assert.equal(requests.length,count);
selector.dispose();await selector.refresh();assert.equal(requests.length,count);

// Opaque session references are sent in a header, never in GET URLs or persisted state.
vm.runInContext("credentialReferenceMemory.set('dashscope','ghopt_session_reference')",context);
context.fixture.provider.value='dashscope';
const next=vm.runInContext('createApiModelSelector(fixture)',context);
const withRef=next.refresh();
assert.equal(requests.at(-1).options.headers['X-HuTX-Optimizer-Reference'],'ghopt_session_reference');
assert.equal(requests.at(-1).url.includes('ghopt_'),false);
next.dispose();resolvers.shift()({models:[{id:'should-not-render'}]});await withRef;
assert.equal(next.root.children[1].children.some(row=>row.value==='should-not-render'),false);
await turn();
console.log('PASS: selection, stale models, vision compatibility, search, provider races, failure fallback, disposal and credential headers');
