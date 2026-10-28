import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import { bindResponsiveFalHosts } from "./responsive_dom_host.js";
import {installStudioTheme as _installStudioTheme} from "./studio_theme.js";

const FAL_CREDENTIAL_ROUTE = "/hutx/minimax-h3/fal-credential";

export function createFalCredentialPanel(api) {
    const make = (tag, cls, text = "") => {
        const el = document.createElement(tag); el.className = cls; el.textContent = text; return el;
    };
    const root = make("details", "hutx-fal-credentials");
    root.innerHTML = `<style>
    .hutx-fal-credentials{box-sizing:border-box;width:100%;max-width:none;min-width:0;align-self:stretch;padding:8px;border:1px solid #385163;border-radius:6px;background:#17232e;color:#c9dfe8;font:12px/1.5 Arial;overflow:auto}
    .hutx-fal-credentials [hidden]{display:none!important}.hutx-fal-credentials summary{cursor:pointer;font-weight:600}.hutx-fal-credentials input{box-sizing:border-box;width:100%;min-width:0;margin:7px 0;padding:7px;background:#101b24;color:#dce8ef;border:1px solid #385163;border-radius:4px}
    .hutx-fal-credentials button{padding:5px 7px;background:#163b4b;border:1px solid #417087;border-radius:4px;color:#c9e9f3;cursor:pointer}.hutx-fal-credentials button:disabled{opacity:.5;cursor:wait}.hutx-fal-actions{display:flex;gap:5px;flex-wrap:wrap}.hutx-fal-status{color:#aac9d6;margin:7px 0}.hutx-fal-active{color:#8bdce7}.hutx-fal-note{font-size:10px;color:#8fa7b3;margin-top:5px}.hutx-fal-feedback,.hutx-fal-confirm{padding:7px;border-radius:5px;margin-top:7px;white-space:pre-line;overflow-wrap:anywhere}.hutx-fal-feedback[data-kind=success]{background:#153c2d;color:#88e8ae}.hutx-fal-feedback[data-kind=error]{background:#472629;color:#ffacac}.hutx-fal-feedback[data-kind=warning]{background:#49391d;color:#ffd278}.hutx-fal-feedback[data-kind=info]{background:#193344;color:#a8d8f2}.hutx-fal-confirm{background:#283845}.hutx-fal-confirm button{margin:5px 5px 0 0}
    </style>`;
    root.append(make("summary", "", "Fal API 凭证管理"));
    const status = make("div", "hutx-fal-status");
    const active = make("div", "hutx-fal-active", "正在读取凭证状态…");
    const sessionState = make("div", "hutx-fal-session-state");
    const persistedState = make("div", "hutx-fal-persisted-state");
    const priority = make("div", "hutx-fal-note");
    status.append(active,sessionState,persistedState,priority);
    const input = make("input", "hutx-fal-key"); input.type = "password"; input.autocomplete = "off";
    input.placeholder = "输入 FAL_KEY"; input.setAttribute("aria-label", "Fal API Key");
    const actions = make("div", "hutx-fal-actions");
    const session = make("button", "hutx-fal-session", "仅本次会话");
    const save = make("button", "hutx-fal-save", "安全保存到本机");
    const remove = make("button", "hutx-fal-delete", "删除本机凭证");
    const feedback = make("div", "hutx-fal-feedback");feedback.hidden=true;feedback.setAttribute('role','status');feedback.setAttribute('aria-live','polite');
    const confirm = make("div", "hutx-fal-confirm"); confirm.hidden=true;
    const yes = make("button", "hutx-fal-confirm-delete", "确定删除");
    const no = make("button", "hutx-fal-cancel-delete", "取消");
    confirm.append(make('div','','确定删除本机安全保存的 FAL_KEY？'),yes,no);
    const note=make("div", "hutx-fal-note", "仅状态可见，不显示凭证内容。Windows 本机存储使用当前用户 DPAPI。");
    actions.append(session, save, remove);
    root.append(status,input,actions,confirm,feedback,note);
    let busy=false, current=null;
    const message=(kind,text)=>{feedback.hidden=false;feedback.setAttribute('data-kind',kind);feedback.textContent=text;};
    const buttons=()=>{input.disabled=session.disabled=save.disabled=remove.disabled=yes.disabled=busy;};
    function show(data) {
        const source=data?.active_source;
        const keys=['configured','environment_configured','session_configured','persisted_configured','persistence_supported'];
        if(!['environment','session','persisted','none'].includes(source)||keys.some(k=>typeof data[k]!=='boolean')) throw Error('status contract');
        current=Object.fromEntries(keys.map(k=>[k,data[k]]));current.active_source=source;
        active.textContent='当前生效： '+({environment:'● 环境变量 FAL_KEY',session:'● 本次会话',persisted:'● 本机安全存储',none:'○ 未配置'}[source]);
        sessionState.textContent='会话凭证： '+(current.session_configured?'✓ 已配置':'○ 未配置');
        persistedState.textContent='本机凭证： '+(current.persisted_configured?'✓ Windows DPAPI 已保存':'○ 未保存');
        priority.textContent=current.environment_configured?'环境变量优先级最高':'优先级：环境变量 > 本次会话 > 本机安全存储';
        input.placeholder=current.environment_configured?'环境变量已配置，可输入临时凭证但当前不会优先使用'
            :current.session_configured?'输入新的 FAL_KEY 以替换会话凭证'
            :current.persisted_configured?'输入新的 FAL_KEY 以更新本机凭证':'输入 FAL_KEY';
        input.title=input.placeholder;
        note.textContent=current.persistence_supported?'Windows DPAPI · Current User；只删除本机凭证不会影响环境变量或会话。':'当前系统暂不支持本机持久安全存储，请使用环境变量或会话凭证。';
    }
    async function request(method='GET',storage) {
        if(busy)return;
        if(method==='POST'&&!input.value.trim()){message('error','✕ 请先输入 FAL_KEY');return;}
        if(method==='POST'&&storage==='persisted'&&current?.persistence_supported===false){message('error','✕ 当前系统暂不支持本机持久安全存储');return;}
        busy=true;buttons();confirm.hidden=true;
        if(method!=='GET')message('info',method==='POST'?'● 正在安全保存...':'● 正在删除本机凭证...');
        let body;
        try {
            if(method==='POST') {
                body=new Blob([JSON.stringify({key:input.value,storage})],{type:'application/json'});
                input.value='';
            }
            const pending=api.fetchApi(FAL_CREDENTIAL_ROUTE,{method,body,cache:'no-store'});body=undefined;
            const response=await pending;
            if(!response.ok)throw Error('credential operation');
            show(await response.json());
            if(method==='DELETE')message('success','✓ 已删除本机安全凭证');
            if(method==='POST') {
                if(storage==='session') {
                    if(current.active_source==='environment')message('warning','✓ 会话凭证已保存\n但当前仍由环境变量 FAL_KEY 生效');
                    else message('success','✓ 已保存到本次会话\nComfyUI 重启后失效');
                } else if(current.active_source==='environment')message('warning','✓ 本机凭证已保存\n当前仍由环境变量 FAL_KEY 生效');
                else if(current.active_source==='session')message('warning','✓ 本机凭证已保存\n当前仍由本次会话凭证生效');
                else message('success','✓ 已使用 Windows DPAPI 安全保存到本机\nComfyUI 重启后仍可使用');
            }
        } catch {
            // Never render an echoed error or server-supplied secret metadata.
            message('error',method==='GET'?'✕ 无法读取凭证状态，请确认 ComfyUI 已重启更新。':method==='POST'?'✕ 凭证保存失败，请重新输入后重试。':'✕ 删除失败，请重试。');
        } finally {
            body=undefined;busy=false;buttons();
        }
    }
    input.oninput=()=>{if(feedback.getAttribute('data-kind')==='error')feedback.hidden=true;};
    session.onclick=()=>request('POST','session');save.onclick=()=>request('POST','persisted');
    remove.onclick=()=>{
        if(busy)return;
        if(!current){message('error','✕ 请先读取凭证状态后重试。');return;}
        if(!current.persisted_configured){message('info','当前没有本机安全凭证可删除。');return;}
        confirm.hidden=false;
    };
    yes.onclick=()=>request('DELETE');no.onclick=()=>{confirm.hidden=true;};
    root.ontoggle=()=>{if(root.open)request();else{input.value='';confirm.hidden=true;}};
    return {element:root,refresh:()=>request(),destroy:()=>{input.value='';root.remove();}};
}

app.registerExtension({
    name:"HuTX.MiniMaxH3Studio.FalCredentials",
    beforeRegisterNodeDef(nodeType,nodeData) {
        if(nodeData.name!=="FalH3MaxVideoGH")return;
        const created=nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated=function() {
            const result=created?.apply(this,arguments);
            if(!this.addDOMWidget||this._hutxFalCredentials)return result;
            const panel=createFalCredentialPanel(api);
            const widget=this.addDOMWidget('hutx_fal_credentials','hutx_fal_credentials',panel.element,{serialize:false});
            widget.serialize=false;widget.options||={};widget.options.serialize=false;widget.serializeValue=()=>undefined;
            widget.options.getMinHeight=()=>panel.element.open?340:40;
            widget.options.getHeight=()=>panel.element.open?'340px':'40px';
            const hosts=bindResponsiveFalHosts(this);
            const toggle=panel.element.ontoggle;
            panel.element.ontoggle=()=>{
                toggle();const size=this.computeSize?.();
                if(size)this.setSize?.([this.size?.[0]||size[0],Math.max(this.size?.[1]||0,size[1])]);
                this.setDirtyCanvas?.(true,true);
            };
            this._hutxFalCredentials=true;
            const removed=this.onRemoved;
            this.onRemoved=function(){hosts.destroy();panel.destroy();return removed?.apply(this,arguments);};
            panel.refresh();return result;
        };
    },
});
