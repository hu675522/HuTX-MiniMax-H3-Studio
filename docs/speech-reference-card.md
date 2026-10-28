# 默认参考声线与音频素材卡片

2026-09-13。新建 GHSpeechInputGH 默认 clone/参考声线，旧工作流显式保存的 preset 选择保留。

参考录音使用单一素材卡片：上传/更换 WAV、试听、编辑显示名称、移除。不展示内部路径、参考原文或原来的独立「保存本机音色」表单。改名仅修改工作流中的显示名称，不重命名磁盘文件、不改变音频身份；移除只解除节点引用，不删除源文件。隐藏字段仍支持旧工作流和既有预设音色数据。

本地参考原文为空时，独立 worker 使用已经安装的 Whisper base 在 CPU 上自动识别，之后沿用 CosyVoice zero-shot；提供原文的旧工作流继续使用其原文。识别文本只在子进程内使用，不回填 workflow、报告或浏览器。新上传录音会清除旧录音原文与旧采用引用，防止错配。

模型为 `.speech-runtime/models/quality/base.pt`，SHA-256 固定为 `ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e`。本机已有模型与 Whisper 依赖，不做自动下载、不修改 ComfyUI Python。其他机器需要运行已有质量模型安装流程；缺失/校验失败/识别无有效文本会显示明确错误，不自动切换云端。自动识别可能有同音误识，生成结果仍需试听确认。

验证：新增 5 项自动识别测试，全量 797 passed（1 条已有 pynvml 警告）。真实隔离 ComfyUI + Edge 验证默认值、五档宽度、上传试听、显示名称保存重载、移除及路径/原文不可见。独立离线识别通过；完整本地 `/generate` 以空 reference_text 生成 1.48 秒非 Mock 音频，用时约 48 秒，无云端请求。该样例是链路验证，不等同声线相似度/逐字听感验收。

源文件：speech_nodes.py、speech_validation.py、speech_worker.py、speech_local.py、speech_errors.py、web/js/speech_input.js、web/js/speech_controller.js。测试：test_speech_reference_card.py、smoke_reference_transcript.py、test_speech_stage_two.py、browser_speech_stage_two.mjs、browser_speech_comfy_polish.mjs。
