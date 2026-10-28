// Executes the actual Cloud panel/controller serializers with a tiny DOM shim.
// All API operations are intercepted. No network, models, storage, or uploads.
import fs from 'node:fs';
import vm from 'node:vm';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = new URL('../', import.meta.url);
const read = name => fs.readFileSync(new URL(name, root), 'utf8');
const stripImports = text => text.replace(/^import[\s\S]*?from\s+["'][^"']+["'];\s*/gm, '');
const optimizer = read('web/js/prompt_optimizer_shared.js').replace(/\bexport /g, '');
const shared = read('web/js/video_input_components.js').replace(/\bexport /g,'') + '\n' + read('web/js/responsive_dom_host.js').replace(/\bexport /g, '') + '\n' + read('web/js/gh_video_input_shared.js').replace(/\bexport /g, '');
const cloud = stripImports(read('web/js/gh_cloud_video_input.js'));
const errors = [];
class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.value = ''; this.listeners = {}; this.attributes = {}; this.selectionStart = 0; this.selectionEnd = 0;
        this.classList = {add(){},remove(){},toggle(){}}; }
    append(...items) { this.children.push(...items); for (const item of items) if (item && typeof item === 'object') item.parent = this; }
    appendChild(item) { this.append(item); return item; }
    replaceChildren(...items) { this.children = items; }
    setAttribute(key, value) { this.attributes[key] = value; }
    querySelector(selector) { return this.children.find(el => el.attributes?.['aria-selected'] === 'true') || null; }
    scrollIntoView() {}
    getBoundingClientRect() { return {left:100, right:520, top:100, bottom:220, width:420, height:120}; }
    getClientRects() { return [this.getBoundingClientRect()]; }
    get clientWidth() { return 418; }
    get offsetWidth() { return 420; }
    get offsetHeight() { return 120; }
    get scrollTop() { return 0; }
    get scrollLeft() { return 0; }
    get scrollHeight() { return 100; }
    closest() { return null; }
    focus() { context.document.activeElement = this; }
    setRangeText(text, start, end) { this.value = this.value.slice(0,start) + text + this.value.slice(end); this.selectionStart = this.selectionEnd = start + text.length; }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(item => item !== this); }
    addEventListener(event, handler) { (this.listeners[event] ||= []).push(handler); }
    removeEventListener(event, handler) { this.listeners[event] = (this.listeners[event] || []).filter(item => item !== handler); }
    emit(event, extras = {}) {
        const e = {key:'', preventDefault(){this.prevented=true;}, stopPropagation(){}, ...extras};
        this['on' + event]?.(e);
        for (const handler of this.listeners[event] || []) handler(e);
        return e;
    }
}
const callbacks = [];
const body = new Element('body');
const alerts = [];
const context = vm.createContext({
    console: {error: msg => errors.push(msg)}, URLSearchParams, AbortController,
    setTimeout, clearTimeout, setInterval, clearInterval, performance,
    addEventListener(){}, removeEventListener(){}, innerWidth:1024, innerHeight:768,
    getComputedStyle:()=>({borderLeftWidth:'1px',borderRightWidth:'1px',fontSize:'12px',lineHeight:'18px'}),
    structuredClone: value => JSON.parse(JSON.stringify(value)),
    document: {body, createElement: tag => new Element(tag), createTextNode: text => text},
    Option: class extends Element { constructor(text, value) { super('option'); this.textContent = text; this.value = value; } },
    Blob, alert: message => alerts.push(message),
    navigator: {language:input.locale || 'en'}, requestAnimationFrame: fn => callbacks.push(fn),
    INPUT: input,
});
let source = optimizer;
if (input.legacy) {
    // Reproduce the exact pre-fix serializer boundary, not a handwritten state.
    source = source.replaceAll('prompt_profile: "auto", ', '').replace('optimizer_state_version: OPTIMIZER_STATE_VERSION,', '')
        .replace('config: serializePublicOptimizerConfig(settings),', 'config: sanitizeOptimizerConfig(settings),');
}
vm.runInContext(`
let extension;
globalThis.requests = [];
globalThis.queueCalls = 0;
const credentialStore = structuredClone(INPUT.initialCredentials || {});
const credentialSessions = {};
const api = {fetchApi: async (url, options = {}) => {
    const body = options.body ? JSON.parse(await options.body.text()) : null;
    requests.push({url, method:options.method || 'GET', body});
    let data, status = 200;
    if (INPUT.secureCredentials && url.startsWith('/hutx/minimax-h3/prompt-optimizer/credential?')) {
        const provider = new URLSearchParams(url.split('?')[1]).get('provider');
        if (options.method === 'POST') credentialStore[provider] = true;
        if (options.method === 'DELETE') delete credentialStore[provider];
        const environment = (INPUT.environment || []).includes(provider), session = !!credentialSessions[provider], persisted = !!credentialStore[provider];
        data = {provider, configured:environment || session || persisted,active_source:environment?'environment':session?'session':persisted?'persisted':'none',environment_configured:environment,session_configured:session,persisted_configured:persisted,persistence_supported:true};
    } else if (url.endsWith('/config')) data = INPUT.config;
    else if ((INPUT.runtime || INPUT.secureCredentials) && url.endsWith('/secret')) {
        data = INPUT.secretError ? {error:'Secret exchange failed'} : {credential_ref:'ghopt_test_xxx'};
        credentialSessions[body.provider] = true;
        if (INPUT.secretError) status = 400;
    } else if (INPUT.runtime && url.endsWith('/optimize')) {
        if (globalThis.optimizeHook) await globalThis.optimizeHook();
        data = INPUT.optimizeError ? {error:INPUT.optimizeError} : {prompt:INPUT.optimizedPrompt || 'Optimized paper boat scene.',report:'{"status":"optimized"}'};
        if (INPUT.optimizeError) status = 400;
    } else if (url.endsWith('/cancel')) data = {cancelled:true};
    else throw new Error('Unexpected API operation: ' + url);
    return {ok:status === 200,status,text:async()=>JSON.stringify(data)};
}};
const app = {graph:{}, registerExtension:value=>{extension=value;}, queuePrompt:async()=>{queueCalls++; return {prompt_id:'mock'};}};
` + source + '\n' + shared + '\n' + cloud + `
class Node {
    constructor(saved) {
        this.properties = saved ? {gh_cloud_video_state:JSON.stringify(saved)} : {};
        this.graph = app.graph; this.mode = 0; this.size = [460,620];
        this.widgets = ['main_mode','prompt','aspect','duration_seconds',...GH_CLOUD_MEDIA_SLOTS,
            'gh_cloud_state_json','optimizer_enabled','optimized_prompt','optimizer_report'].map(name=>({name,value:''}));
        this.widgets.find(w=>w.name==='prompt').value = 'A paper boat sails.';
        this.widgets.find(w=>w.name==='aspect').value = '16:9';
        this.widgets.find(w=>w.name==='duration_seconds').value = 5;
        this.onNodeCreated();
    }
    addDOMWidget(name, type, root) {this.panel = root; return {options:{}};}
    setSize() {}
    setDirtyCanvas() {}
}
extension.beforeRegisterNodeDef(Node, {name:'GHCloudVideoInputGH'});
globalThis.node = new Node(INPUT.state);
globalThis.createNode = saved => new Node(saved);
globalThis.app = app;
globalThis.serialize = () => {
    node.onSerialize();
    const state = JSON.parse(node.widgets.find(w=>w.name==='gh_cloud_state_json').serializeValue());
    return {state, properties:node.properties, widgets_values:node.widgets.map(w=>w.value)};
};
`, context);
while (callbacks.length) callbacks.shift()();
// Automatic hook loads actual /config shape; auto_optimize=false stops before LLM.
if (input.loadConfig) await context.app.queuePrompt();
const runtime = {};
const credentialSnapshots = [];
const profileSnapshots = [];
const historySnapshots = [];
const descendants = el => [el,...(el.children || []).flatMap(item=>typeof item==='object'?descendants(item):[])];
if (input.duringOptimize) context.optimizeHook = async () => {
    const panel=descendants(context.node.panel);
    const prompt=panel.find(el=>el.className==='gh-cloud-prompt');
    if (input.duringOptimize === 'edit' || input.duringOptimize === 'editBack') {
        const previous=prompt.value;prompt.value='User edited while waiting.';prompt.emit('input');
        if(input.duringOptimize === 'editBack') {prompt.value=previous;prompt.emit('input');}
    } else if(input.duringOptimize === 'cancel') await panel.find(el=>el.className==='gh-opt-cancel').onclick();
    else if(input.duringOptimize === 'configure') {
        context.node.onConfigure({properties:{gh_cloud_video_state:JSON.stringify(input.replacementState)}});
        while(callbacks.length) callbacks.shift()();
    } else if(input.duringOptimize === 'duplicate') await panel.find(el=>el.className==='gh-opt-run').onclick();
};
if (input.profileActions) {
    const all = el => [el,...(el.children || []).flatMap(item=>typeof item==='object'?all(item):[])];
    await all(context.node.panel).find(el=>el.className==='gh-opt-configure').onclick();
    for (const action of input.profileActions) {
        if (action.type==='mode') all(context.node.panel).find(el=>el.className==='gh-cloud-modes').children[action.index].onclick();
        const select=all(body).find(el=>el.className==='gh-opt-profile');
        if (action.type==='profile') {select.value=action.value;select.onchange();}
        await new Promise(resolve=>setTimeout(resolve,230));
        const recommendation=all(body).find(el=>el.className==='gh-opt-profile-recommendation');
        profileSnapshots.push({value:select.value,options:select.children.map(el=>el.value),text:recommendation.textContent,hidden:recommendation.hidden});
    }
    all(body).find(el=>el.tag==='button' && ['Cancel','取消'].includes(el.textContent)).onclick();
}
if (input.credentialActions) {
    const all = el => [el,...(el.children || []).flatMap(item=>typeof item==='object'?all(item):[])];
    await all(context.node.panel).find(el=>el.className==='gh-opt-configure').onclick();
    await new Promise(resolve=>setTimeout(resolve,0));
    const form = () => ({key:all(body).find(el=>el.type==='password'),provider:all(body).filter(el=>el.tag==='select')[1],panel:all(body).find(el=>el.className==='gh-opt-secure-credentials')});
    for (const action of input.credentialActions) {
        const ui=form();
        if(action.type==='input') ui.key.value=action.value;
        else if(action.type==='provider') {ui.provider.value=action.value;ui.provider.emit('change');}
        else if(action.type==='session' || action.type==='persisted' || action.type==='delete') {
            const buttons=all(ui.panel).filter(el=>el.tag==='button');
            const pending=buttons[{session:0,persisted:1,delete:2}[action.type]].onclick();
            runtime.inputDuringCredentialSave=ui.key.value;await pending;
        }
        await new Promise(resolve=>setTimeout(resolve,0));
        credentialSnapshots.push({status:ui.panel.children[0].textContent,feedback:ui.panel.children[2].textContent,kind:ui.panel.children[2].attributes['data-state'],placeholder:ui.key.placeholder,key:ui.key.value});
    }
    all(body).find(el=>el.tag==='button' && ['Cancel','取消'].includes(el.textContent)).onclick();
}
if (input.runtime) {
    const all = el => [el, ...(el.children || []).flatMap(item => typeof item === 'object' ? all(item) : [])];
    const bar = all(context.node.panel).find(el => el.className === 'gh-opt-bar');
    const optimize = all(bar).find(el => el.className === 'gh-opt-run');
    const configure = all(bar).find(el => el.className === 'gh-opt-configure');
    const form = () => {
        const elements = all(body);
        return {
            key:elements.find(el => el.type === 'password'),
            provider:elements.filter(el => el.tag === 'select')[1],
            auto:elements.filter(el => el.type === 'checkbox')[1],
            status:elements.find(el => el.className === 'gh-opt-credential-status'),
            profile:elements.find(el => el.className === 'gh-opt-profile'),
            save:elements.find(el => el.tag === 'button' && ['Save','保存'].includes(el.textContent)),
            cancel:elements.find(el => el.tag === 'button' && ['Cancel','取消'].includes(el.textContent)),
        };
    };
    await configure.onclick();
    let ui = form();
    runtime.initialStatus = ui.status.textContent;
    if (input.save !== false) {
        ui.provider.value = 'dashscope'; ui.provider.onchange();
        ui.auto.checked = Boolean(input.automatic);
        ui.profile.value = input.profile || 'auto';
        ui.key.value = 'TEST_SECRET_123';
        if(input.persistSave) {
            await all(body).find(el=>el.tag==='button' && ['安全保存到本机','Save securely on this computer'].includes(el.textContent)).onclick();
        }
        const saving = ui.save.onclick();
        runtime.keyDuringExchange = ui.key.value;
        await saving;
        runtime.keyAfterSave = ui.key.value;
        runtime.saved = context.serialize();
        runtime.legacyStatusCount = all(bar).filter(el => el.className === 'gh-opt-status').length;
        if (input.secretError) ui.cancel.onclick();
    } else ui.cancel.onclick();
    await configure.onclick(); ui = form();
    runtime.reopenedKey = ui.key.value;
    runtime.reopenedStatus = ui.status.textContent;
    runtime.reopenedProfile = ui.profile.value;
    ui.provider.value = 'custom'; ui.provider.onchange();
    runtime.otherProviderStatus = ui.status.textContent;
    ui.cancel.onclick();
    if (input.automatic) await context.app.queuePrompt();
    else await optimize.onclick();
    // Flush any configuration popup opened by the missing-credential path.
    await new Promise(resolve => setTimeout(resolve, 0));
    runtime.queueCalls = context.queueCalls;
    runtime.final = context.serialize();
    for (const overlay of [...body.children].filter(el=>el.className === 'gh-opt-overlay')) overlay.remove();
    await configure.onclick(); ui = form();
    runtime.afterRunStatus = ui.status.textContent;
    ui.cancel.onclick();
}
for (const action of input.historyActions || []) {
    if(action.type==='reload') {
        const saved=JSON.parse(JSON.stringify(context.serialize().state));
        context.node.onRemoved();
        context.node=context.createNode(saved);
        while(callbacks.length) callbacks.shift()();
    } else if(action.type==='configure') {
        context.node.onConfigure({properties:{gh_cloud_video_state:JSON.stringify(context.serialize().state)}});
        while(callbacks.length) callbacks.shift()();
    } else if(action.type==='edit') {
        const prompt=descendants(context.node.panel).find(el=>el.className==='gh-cloud-prompt');
        prompt.value=action.value;prompt.emit('input');
    } else if(action.type==='restore' || action.type==='apply') {
        descendants(context.node.panel).find(el=>el.className==='gh-prompt-'+action.type).onclick();
    }
    const elements=descendants(context.node.panel);
    elements.find(el=>el.className==='gh-prompt-tabs').children.find(el=>el.value==='compare').onclick();
    historySnapshots.push({...context.serialize(),
        views:descendants(context.node.panel).filter(el=>el.className==='gh-prompt-readonly').map(el=>({text:el.children[1].value,readOnly:el.children[1].readOnly})),
        empty:descendants(context.node.panel).find(el=>el.className==='gh-prompt-view').children[0]?.textContent,
    });
}
const ux = [];
if (input.uxActions) {
    const all = el => [el, ...(el.children || []).flatMap(item => typeof item === 'object' ? all(item) : [])];
    const textarea = all(context.node.panel).find(el => el.tag === 'textarea');
    const menu = all(body).find(el => el.className === 'gh-cloud-picker');
    for (const action of input.uxActions) {
        if (action.type === 'type') {
            textarea.selectionStart = 0; textarea.selectionEnd = textarea.value.length;
            textarea.emit('beforeinput', {inputType:'insertText', data:action.text});
            textarea.focus(); textarea.value = action.text;
            textarea.selectionStart = textarea.selectionEnd = action.caret ?? action.text.length;
            textarea.emit('input');
        } else if (action.type === 'insert') {
            textarea.focus();
            textarea.emit('beforeinput', {inputType:'insertText', data:action.text});
            textarea.setRangeText(action.text, textarea.selectionStart, textarea.selectionEnd);
            textarea.emit('input');
        } else if (action.type === 'ratio') {
            all(context.node.panel).find(el=>el.className === 'gh-ratio-trigger').onclick();
            all(body).find(el=>el.className === 'gh-ratio-popup').children.find(el=>el.value === action.value).onclick();
        } else if (action.type === 'tab') {
            all(context.node.panel).find(el=>el.className === 'gh-prompt-tabs').children.find(el=>el.value === action.value).onclick();
        } else if (action.type === 'history') {
            all(context.node.panel).find(el=>el.className === 'gh-prompt-'+action.value).onclick();
        } else if (action.type === 'key') textarea.emit('keydown', {key:action.key});
        else if (action.type === 'click') menu.children[action.index].onclick();
        else if (action.type === 'delete') {
            const tag = all(context.node.panel).find(el => el.className === 'gh-cloud-tag' && el.textContent === action.tag);
            tag.parent.children.find(el => el.className === 'gh-cloud-remove').onclick();
        } else if (action.type === 'mode') {
            all(context.node.panel).find(el => el.className === 'gh-cloud-modes').children[action.index].onclick();
        } else if (action.type === 'restore') {
            context.node.properties.gh_cloud_video_state = JSON.stringify(action.state);
            context.node.onConfigure({properties:context.node.properties});
            while (callbacks.length) callbacks.shift()();
        }
        ux.push({hidden:menu.hidden, text:textarea.value, caret:textarea.selectionStart,
            aspect:all(context.node.panel).find(el=>el.className === 'gh-ratio-trigger').value,
            aspectLabel:all(context.node.panel).find(el=>el.className === 'gh-ratio-trigger').children[1].textContent,
            history:all(context.node.panel).filter(el=>el.className === 'gh-prompt-readonly').map(el=>({title:el.children[0].textContent,text:el.children[1].value,readOnly:el.children[1].readOnly})),
            rows:menu.children.filter(el => el.tag === 'button').map(el => ({name:el.children[0].textContent,
                filename:el.children[1].textContent, title:el.title, selected:el.attributes['aria-selected']}))});
    }
}
process.stdout.write(JSON.stringify({...context.serialize(), errors, alerts, requests:context.requests, runtime, ux, credentialSnapshots, profileSnapshots, historySnapshots}, null, 2));
