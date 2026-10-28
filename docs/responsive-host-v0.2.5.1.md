# V0.2.5.1 DOM host 审计

## 实机只读观察

2026-09-06，在用户当前 Chrome 的 `http://127.0.0.1:8188/` 页面读取 DOM。
没有修改用户 workflow，也没有执行 Queue、LLM 或 Fal 请求。

Cloud 与 Fal 的父链如下。两者 root 的 computed width 均为 424px，
rect width 分别为 385.454559 / 385.454590px，canvas scale 为 0.909091。

| 层级 | class | computed width | rect width | max-width | min-width | display | flex | align-self |
|---|---|---:|---:|---|---|---|---|---|
| root | gh-cloud-video-root / hutx-fal-credentials，均附加 h-full w-full | 424px | 385.455px | none | 0px | block | 0 1 auto | auto |
| parent | dom-widget size-full | 424px | 385.455px | none | 0px | block | 0 1 auto | auto |
| parent² | isolate | 1920px | 1920px | none | 0px | block | 0 1 auto | auto |
| parent³ | graph-canvas-container | 1920px | 1920px | none | 0px | block | 0 1 auto | auto |
| parent⁴ | comfyui-body grid size-full overflow-hidden | 1920px | 1920px | none | auto | grid | 0 1 auto | auto |
| parent⁵ | relative size-full overflow-hidden | 1920px | 1920px | none | 0px | block | 0 1 auto | auto |
| parent⁶ | div（无 class） | 1920px | 1920px | none | 0px | block | 0 1 auto | auto |
| parent⁷ | body.litegraph.grid | 1920px | 1920px | stretch | stretch | grid | 0 1 auto | auto |

除 parent 外，上述元素 inline style 均为空。
Cloud parent inline：
`position: fixed; transform-origin: 0px 0px; transform: scale(0.909091); left: 96.0879px; top: 161.688px; width: 424px; height: 1373.22px; z-index: 2; pointer-events: auto; opacity: 1; clip-path: none; will-change: clip-path;`
Fal parent inline：
`position: fixed; transform-origin: 0px 0px; transform: scale(0.909091); left: 662.424px; top: 456.518px; width: 424px; height: 212px; z-index: 3; pointer-events: auto; opacity: 1; clip-path: none; will-change: clip-path;`

浏览器只读 DOM scope 没有暴露应用 runtime，因此实机 node.size 未在此次读取中取得；
下面的 node.size 和完整 parent-chain 数值由明确隔离的 Edge fixture 记录，不能误称为用户 workflow 数值。

## 本机 ComfyUI 源码依据

已读取安装的 comfyui_frontend_package/static/assets：
- GraphView-Cc2GkGnZ.js 的 DomWidgets.updateWidgets 使用
  `(widget.width ?? node.width) - widget.margin * 2` 生成 host width。
- settingStore-KkBYyEnh.js 的侧栏 CanvasWidget.draw 将 parent.clientWidth 写入 `widget.width`。
- 同文件 BaseDOMWidget.draw 调用 `options.onDraw`，addWidget 在 resize 时调用 `options.afterResize`。

因此不能把 fixed host 的 width 改成 100%：它的 parent 是整个画布。
插件释放自己 DOM widget 的 width 覆盖，让 ComfyUI 重算 host；root 和 host 内部 wrapper
stretch，实际 host 使用 ResizeObserver。Fal 后续添加的 DOM/Component preview widget 同样处理。
不修改 ComfyUI 安装文件，不给 root 写 node.size 像素值。

## Edge mock 验收

运行 `tests/browser_responsive_host_fixture.mjs`，使用相同 DOM 父链、相同 host 宽度表达式，
在 bind 前复现 node.size[0]=720、widget.width=444、host/root=424。
在 bind 后 Cloud/Fal 均得到：

| node | host | root |
|---:|---:|---:|
| 380 | 360 | 360 |
| 460 | 440 | 440 |
| 560 | 540 | 540 |
| 720 | 700 | 700 |
| 900 | 880 | 880 |

另验证侧栏再次写入 width 后的下一次 draw、0.75 缩放、Picker clamp、六种凭证组合、
四色反馈、确认删除和无 secret 回显。完整 computed/inline/rect 链记录在
`.test-artifacts/responsive-host-audit.json`，截图为 `.test-artifacts/host-*.png` 和 `credential-*.png`。
全部请求为 mock。
