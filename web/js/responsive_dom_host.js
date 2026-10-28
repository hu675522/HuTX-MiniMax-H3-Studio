// ComfyUI's canvas overlay uses (widget.width ?? node.width) - 2 * widget.margin.
// Its sidebar CanvasWidget can leave widget.width set to the sidebar's width.
// Release that override; let ComfyUI continue to own gutters, zoom and positioning.
export function createCanvasPanelHost(root) {
    // The renderer owns this stable shell. Workbench leases only its contents,
    // so virtualizing a canvas widget never removes the live editor from a sidebar.
    if(!document.getElementById('hutx-canvas-panel-host-style')){
        const style=document.createElement('style');style.id='hutx-canvas-panel-host-style';
        style.textContent='.hutx-canvas-panel-host{width:100%;height:100%;min-width:0;box-sizing:border-box;overflow:hidden;container-type:inline-size}.hutx-canvas-panel-host>:is(.hutx-speech-root,.gh-local-video-root){height:100%;width:100%}';document.head.append(style);
    }
    const host=document.createElement('div');host.className='hutx-canvas-panel-host';host.append(root);return host;
}

export function bindResponsiveDomHost(node, widget, root, onLayout = () => {}, contentRoot = root) {
    let host = null, disposed = false;
    const stretch = element => Object.assign(element.style, {
        width:"100%", maxWidth:"none", minWidth:"0", boxSizing:"border-box", alignSelf:"stretch", flex:"1 1 auto",
    });
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(() => onLayout()) : null;
    function sync() {
        if(disposed) return;
        widget.width = undefined;
        if(!root?.parentElement) return;
        const next = root.closest?.('.dom-widget') || root.parentElement;
        stretch(root);
        for(let el=root.parentElement;el && el!==next;el=el.parentElement) stretch(el);
        const position = getComputedStyle(next).position;
        if(position !== 'fixed' && position !== 'absolute') stretch(next);
        else Object.assign(next.style,{maxWidth:'none',minWidth:'0',boxSizing:'border-box',alignSelf:'stretch'});
        if(host !== next) {
            observer?.disconnect();host=next;observer?.observe(host);observer?.observe(root);
            if(contentRoot!==root)observer?.observe(contentRoot);
            onLayout();
        }
    }
    const draw = widget.options.onDraw;
    widget.options.onDraw = function(...args) {const result=draw?.apply(this,args);sync();return result;};
    const resize = widget.options.afterResize;
    widget.options.afterResize = function(...args) {const result=resize?.apply(this,args);sync();return result;};
    sync();
    // Mounting is deferred by ComfyUI. onDraw also handles later reparenting.
    const mount = typeof MutationObserver === 'function' && !root?.parentElement
        ? new MutationObserver(()=>{if(root?.parentElement){sync();mount.disconnect();}}) : null;
    mount?.observe(document.body,{childList:true,subtree:true});
    return {sync,destroy(){disposed=true;observer?.disconnect();mount?.disconnect();widget.options.onDraw=draw;widget.options.afterResize=resize;}};
}

export function bindResponsiveFalHosts(node) {
    const bindings = new Map();
    function sync() {
        for(const widget of node.widgets || []) {
            if(!widget.element && !widget.component) continue;
            widget.options ||= {};
            if(!bindings.has(widget)) bindings.set(widget,bindResponsiveDomHost(node,widget,widget.element));
            bindings.get(widget).sync();
        }
    }
    const draw=node.onDrawForeground;
    node.onDrawForeground=function(...args){const result=draw?.apply(this,args);sync();return result;};
    sync();
    return {destroy(){for(const binding of bindings.values())binding.destroy();node.onDrawForeground=draw;}};
}
