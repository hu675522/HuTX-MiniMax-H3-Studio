export const videoInputStyles = `
      <style>
        .gh-cloud-picker{position:fixed;z-index:10040;box-sizing:border-box;overflow:auto;border:1px solid #44849a;border-radius:7px;background:#112532;color:#deedf4;box-shadow:0 7px 24px #0008;padding:4px;font:12px/1.5 Arial,sans-serif}.gh-cloud-picker[hidden]{display:none}.gh-cloud-picker-row{display:flex;gap:10px;align-items:center;width:100%;min-width:0;box-sizing:border-box;border:0;border-radius:4px;padding:7px;text-align:left;color:inherit;background:transparent;cursor:pointer}.gh-cloud-picker-row[aria-selected=true],.gh-cloud-picker-row:hover{background:#1e5266}.gh-cloud-picker-row>span:first-child{flex-shrink:0}.gh-cloud-picker-file{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#aac3ce}.gh-cloud-picker-empty{padding:8px;color:#aac3ce}
        .gh-local-video-root,.gh-cloud-video-root{box-sizing:border-box;width:100%;max-width:none;min-width:0;height:100%;min-height:0;padding:7px;color:#d7e3ef;background:#17232e;font:12px/1.35 Arial,sans-serif;overflow:auto;border-radius:7px}
        .gh-local-video-root [hidden],.gh-cloud-video-root [hidden],.gh-ratio-popup[hidden]{display:none!important}
        .gh-ratio-trigger{display:flex;align-items:center;gap:7px;min-width:0;width:100%;padding:5px;border:1px solid #385163;border-radius:5px;background:#101b24;color:#dce8ef;cursor:pointer;text-align:left}.gh-ratio-trigger>span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gh-ratio-icon{display:inline-block;box-sizing:border-box;flex-shrink:0;border:1.5px solid #6ce0ec;border-radius:2px}
        .gh-ratio-popup{position:fixed;z-index:10041;box-sizing:border-box;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;padding:7px;overflow:auto;background:#112532;border:1px solid #44849a;border-radius:7px;box-shadow:0 7px 24px #0008}.gh-ratio-item{display:flex;flex-direction:column;gap:6px;align-items:center;justify-content:center;min-height:64px;min-width:0;padding:5px;border:1px solid #365564;border-radius:5px;background:#183341;color:#cde3ec;font:11px Arial;cursor:pointer}.gh-ratio-item[aria-selected=true],.gh-ratio-item:hover{border-color:#20bfd3;background:#1e5266}
        .gh-prompt-history{width:100%;min-width:0;box-sizing:border-box}.gh-prompt-history [hidden]{display:none!important}.gh-prompt-header{display:flex;flex-wrap:wrap;align-items:center;gap:5px 14px;margin:5px 0}.gh-prompt-tabs,.gh-prompt-actions{display:flex;gap:5px;flex-wrap:wrap;margin:0}.gh-prompt-tabs button,.gh-prompt-actions button{padding:5px 9px;border:1px solid #385163;border-radius:5px;background:#172b38;color:#a9cad9;cursor:pointer}.gh-prompt-tabs button[aria-selected=true]{background:#147c91;color:white}.gh-prompt-view{display:flex;flex-wrap:wrap;gap:7px}.gh-prompt-readonly{flex:1 1 240px;min-width:0;color:#8bdce7}.gh-prompt-readonly textarea{box-sizing:border-box;width:100%;height:150px;resize:vertical;background:#101b24;color:#dce8ef;border:1px solid #385163;border-radius:5px;padding:7px;font:12px/1.5 Arial}
        .gh-cloud-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;color:#8bdce7}.gh-cloud-task{font-weight:600}.gh-cloud-note{font-size:9px;color:#77909f}
        .gh-cloud-modes{display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-bottom:7px}.gh-cloud-modes button,.gh-cloud-button{border:1px solid #385163;border-radius:5px;background:#1d2c38;color:#b9cbd6;padding:6px;cursor:pointer}.gh-cloud-modes button.active{background:#147c91;border-color:#21a7bd;color:#fff}
        .gh-cloud-controls{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:7px}.gh-cloud-field{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:5px;color:#93a8b5}.gh-cloud-field select,.gh-cloud-field input{min-width:0;width:100%;box-sizing:border-box;border:1px solid #385163;border-radius:4px;background:#101b24;color:#dce8ef;padding:5px}
        .gh-cloud-prompt{box-sizing:border-box;width:100%;height:118px;resize:vertical;border:1px solid #385163;border-radius:5px;background:#101b24;color:#e2edf2;padding:7px;font:12px/1.45 Arial,sans-serif;outline:none}.gh-cloud-prompt:focus{border-color:#20a9bd}
        .gh-cloud-section{margin-top:7px;padding:7px;border:1px solid #314756;border-radius:6px;background:#111c25}.gh-cloud-section-title{margin-bottom:5px;color:#b9d5df}.gh-cloud-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}.gh-cloud-keyframes{grid-template-columns:1fr 1fr}.gh-cloud-keyframes .gh-cloud-audio{grid-column:1/-1}
        .gh-cloud-slot{position:relative;box-sizing:border-box;min-width:0;min-height:75px;border:1px dashed #375768;border-radius:5px;background:#0d1820;overflow:hidden}.gh-cloud-slot.empty{display:flex;align-items:center;justify-content:center;color:#55798d;cursor:pointer;padding:7px;text-align:center}.gh-cloud-slot.drag{border-color:#1ec2d7;background:#17323e}.gh-cloud-preview{display:block;width:100%;height:72px;object-fit:cover;background:#091117}.gh-cloud-audio .gh-cloud-preview{height:34px;margin-top:22px}.gh-cloud-file{padding:3px 25px 3px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#8da5b2;font-size:8px}.gh-cloud-remove{position:absolute;right:3px;top:3px;border:0;border-radius:3px;background:rgba(17,29,38,.85);color:#cf8a91;cursor:pointer}.gh-cloud-tag{position:absolute;left:3px;top:3px;border:0;border-radius:3px;background:rgba(17,86,101,.88);color:#dff8fb;font-size:9px;cursor:pointer;padding:2px 4px}.gh-cloud-meta{display:flex;align-items:center;gap:5px;padding:3px 4px;color:#8fa7b3;font-size:9px}.gh-cloud-video-audio-toggle{min-height:28px;margin:4px;padding:5px 7px;border:1px solid #7890a5;border-radius:7px;background:#31485b;color:#edf6fc;font-size:11px;font-weight:650;line-height:1.25;cursor:pointer;user-select:none}.gh-cloud-video-audio-toggle:hover{border-color:#59cfff;background:#385469}.gh-cloud-video-audio-toggle:focus-within{outline:2px solid #19a7ff66;outline-offset:1px}.gh-cloud-video-audio-toggle input[type=checkbox]{width:15px;height:15px;flex:0 0 15px;margin:0;accent-color:#19a7ff;cursor:pointer}.gh-cloud-video-audio-toggle[data-muted=true]{border-color:#63d7a2;background:#1e5b48;color:#d8ffec}.gh-cloud-meta input[type=number]{width:58px;border:1px solid #314957;border-radius:3px;background:#101b24;color:#dbe8ef;padding:2px}.gh-cloud-warning{margin-top:5px;color:#d2a16b;font-size:9px}.gh-cloud-empty-note{color:#c9926d;font-size:9px;margin-top:5px}
      </style>`;

function componentElement(tag,className,text='') {const item=document.createElement(tag);item.className=className;item.textContent=text;return item;} 
export function createMediaCard({slot, entry, kind, label, url, getTag, chooseFile, insertTag, removeMedia, onUpdate, trimStartField="trim_start", trimEndField="trim_end", muteLabel}) {


        if (!entry) {
            const empty = componentElement("div", `gh-cloud-slot empty gh-cloud-${kind}`, label(`+ ${slot}`, `＋ ${slot}`));
            empty.onclick = () => chooseFile(slot);
            empty.ondragover = (event) => { event.preventDefault(); empty.classList.add("drag"); };
            empty.ondragleave = () => empty.classList.remove("drag");
            empty.ondrop = (event) => {
                event.preventDefault();
                empty.classList.remove("drag");
                chooseFile(slot, event.dataTransfer?.files?.[0] || null);
            };
            return empty;
        }

        const card = componentElement("div", `gh-cloud-slot gh-cloud-${kind}`);

        let preview;
        if (kind === "image") {
            preview = componentElement("img", "gh-cloud-preview");
            preview.src = url;
        } else if (kind === "video") {
            preview = componentElement("video", "gh-cloud-preview");
            preview.src = url;
            preview.preload = "metadata";
            preview.muted = true;
        } else {
            preview = componentElement("audio", "gh-cloud-preview");
            preview.src = url;
            preview.preload = "metadata";
            preview.controls = true;
        }
        card.appendChild(preview);

        const tag = getTag();
        const tagButton = componentElement("button", "gh-cloud-tag", tag || slot);
        tagButton.title = label("Insert media tag", "插入素材标签");
        tagButton.onclick = () => insertTag(getTag());
        card.appendChild(tagButton);

        const remove = componentElement("button", "gh-cloud-remove", "×");
        remove.onclick = () => { removeMedia(); };
        card.appendChild(remove);
        const filename=componentElement("div", "gh-cloud-file", entry.name); filename.title=entry.name; card.appendChild(filename);

        if (kind === "video") {
            const meta = componentElement("label", "gh-cloud-meta gh-cloud-video-audio-toggle");
            const muted = componentElement("input");
            muted.type = "checkbox";
            muted.checked = Boolean(entry.muted);
            meta.dataset.muted = String(muted.checked);
            meta.title = muteLabel || label("Ignore the reference video's original audio", "忽略参考视频原声");
            muted.onchange = () => { entry.muted = muted.checked; meta.dataset.muted = String(muted.checked); onUpdate(); };
            meta.append(muted, document.createTextNode(muteLabel || label("remove audio before upload", "上传前移除音轨")));
            card.appendChild(meta);
        }
        if (kind === "audio") {
            const meta = componentElement("div", "gh-cloud-meta");
            const start = componentElement("input");
            start.type = "number";
            start.min = "0";
            start.step = "0.01";
            start.value = String(entry[trimStartField] ?? 0);
            const end = componentElement("input");
            end.type = "number";
            end.min = "0";
            end.step = "0.01";
            end.placeholder = label("end", "结束");
            end.value = entry[trimEndField] == null ? "" : String(entry[trimEndField]);
            const updateTrim = () => {
                const startValue = Number(start.value);
                const endValue = end.value === "" ? null : Number(end.value);
                entry[trimStartField] = Number.isFinite(startValue) ? Math.max(0, startValue) : 0;
                entry[trimEndField] = Number.isFinite(endValue) ? Math.max(0, endValue) : null;
                onUpdate();
            };
            start.onchange = updateTrim;
            end.onchange = updateTrim;
            meta.append(document.createTextNode(label("trim", "裁切")), start, document.createTextNode("→"), end);
            card.appendChild(meta);
        }
        return card;
    }


