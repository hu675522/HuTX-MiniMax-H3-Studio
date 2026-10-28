import fs from 'node:fs';
import vm from 'node:vm';
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const read=name=>fs.readFileSync(new URL('../web/js/'+name,import.meta.url),'utf8').replace(/^import .*;$/gm,'').replace(/\bexport /g,'');
const source=read('responsive_dom_host.js')+'\n'+read('fal_credentials.js');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.value='';this.attributes={};this.style={};}
 append(...items){this.children.push(...items);}
 setAttribute(k,v){this.attributes[k]=v;}
 getAttribute(k){return this.attributes[k];}
 remove(){}
}
let extension, sessionConfigured=!!input.initialSession,persistedConfigured=!!input.initialPersisted;
const requests=[],errors=[];
const snapshotStatus=()=>({configured:!!(input.environment||sessionConfigured||persistedConfigured),
 active_source:input.environment?'environment':sessionConfigured?'session':persistedConfigured?'persisted':'none',
 environment_configured:!!input.environment,session_configured:sessionConfigured,persisted_configured:persistedConfigured,persistence_supported:true});
const ctx=vm.createContext({Blob,document:{createElement:tag=>new Element(tag)},
 localStorage:new Proxy({}, {get(){throw Error('storage forbidden');}}),sessionStorage:new Proxy({}, {get(){throw Error('storage forbidden');}}),
 console:{log:v=>errors.push(v),error:v=>errors.push(v)},
 app:{registerExtension:ext=>{extension=ext;}},
 api:{fetchApi:async(url,options)=>{
   const body=options.body?JSON.parse(await options.body.text()):undefined;
   requests.push({url,method:options.method,body});
   if(options.method==='POST'&&!input.fail){if(body.storage==='session')sessionConfigured=true;else persistedConfigured=true;}
   if(options.method==='DELETE'&&!input.fail)persistedConfigured=false;
   return {ok:!input.fail,json:async()=>({...snapshotStatus(),...(input.echo?{key:'TEST_FAL_KEY',error:'TEST_FAL_KEY'}:{})})};
 }}});
vm.runInContext(source,ctx);
class Node {
 constructor(){this.properties={legacy:true};this.widgets=[{name:'execution_mode',value:'dry_run'}];this.onNodeCreated();}
 addDOMWidget(name,type,element,options){this.panel=element;const widget={name,element,options};this.widgets.push(widget);return widget;}
}
extension.beforeRegisterNodeDef(Node,{name:'FalH3MaxVideoGH'});
const node=new Node();
const all=el=>[el,...el.children.flatMap(all)];
const find=cls=>all(node.panel).find(el=>el.className===cls);
const flush=async()=>{for(let n=0;n<10;n++)await new Promise(r=>setImmediate(r));};
const ui=()=>({active:find('hutx-fal-active').textContent,session:find('hutx-fal-session-state').textContent,
 persisted:find('hutx-fal-persisted-state').textContent,placeholder:find('hutx-fal-key').placeholder,
 feedback:find('hutx-fal-feedback').textContent,kind:find('hutx-fal-feedback').getAttribute('data-kind'),
 feedbackHidden:find('hutx-fal-feedback').hidden,confirmHidden:find('hutx-fal-confirm').hidden,
 disabled:find('hutx-fal-save').disabled,key:find('hutx-fal-key').value});
await flush();
const initial=ui(),states=[],pendingStates=[];
if(input.actions) {
 for(const action of input.actions) {
  if(action.type==='input'){find('hutx-fal-key').value=action.value;find('hutx-fal-key').oninput();}
  else if(action.type==='save-double') {
   const pending=find('hutx-fal-save').onclick();pendingStates.push(ui());
   await find('hutx-fal-save').onclick();await pending;
  } else {
   const pending=find('hutx-fal-'+action.type).onclick();pendingStates.push(ui());await pending;
  }
  states.push(ui());
 }
} else {
 find('hutx-fal-key').value='TEST_FAL_KEY';
 const pending=find(input.session?'hutx-fal-session':'hutx-fal-save').onclick();
 var during=find('hutx-fal-key').value;
 states.push(ui());await pending;
 var savedStatus=find('hutx-fal-active').textContent;
 var after=find('hutx-fal-key').value;
 await find('hutx-fal-delete').onclick();
 if(!find('hutx-fal-confirm').hidden)await find('hutx-fal-confirm-delete').onclick();
 var deletedStatus=find('hutx-fal-active').textContent;
}
const serialized={properties:node.properties,widgets_values:node.widgets.filter(w=>w.serialize!==false).map(w=>w.value)};
node.onRemoved();
process.stdout.write(JSON.stringify({requests,during,after,savedStatus,deletedStatus,serialized,errors,initial,states,pendingStates}));
