# 口播节点 UI 排版修正

2026-09-12。仅前端排版，不改变模型、凭证、AUDIO 或视频协议。

- 原生 widget 原先只改为自定义 type 并压缩高度，未设置实际 hidden/options.hidden；现在明确隐藏原生 widget 及关联 DOM，保留原类型与序列化行为，移除顶部露出的 workspace 输入。
- 表单统一左边缘、标签间距、输入高度、textarea 行高。Mock checkbox 放到文字左侧并居中对齐。
- 操作按钮等高、间距一致，窄屏自动换行；上传按钮匹配深色主题。
- 能力说明改为模式/模型与说明两列，区分 H3 Max/Turbo，保留所有后端提供的能力事实。
- 独立折叠区加边框与内边距，长文本换行，保持 node host 自适应宽度。

验证：mock Speech 完整交互通过；真实隔离 ComfyUI + Edge 在 380/460/560/720/900px 均无暴露原生控件、无水平溢出，表单左边缘一致，切换本地/云端、克隆/预设及保存重载通过。截图位于 .test-artifacts/speech-polish。

全量 pytest：792 passed，1 条已有 pynvml 弃用警告。未调用真实生成服务。

修改 web/js/speech_input.js，新增 tests/browser_speech_comfy_polish.mjs。
