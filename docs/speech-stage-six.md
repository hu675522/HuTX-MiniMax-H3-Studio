# 第六阶段：发布验证与实机验收记录

> 历史开发记录：文中关于 `.speech-runtime` junction 的描述已过时。当前迁移请参见 [一键安装与迁移](speech-runtime-installer.md)。

日期：2026-09-12。状态：自动化与本地执行检查通过，画面/口型未验收通过。用户已回复「稍后验收」。保持 0.3.1 开发预览，不将待验收包冒充正式 0.4.0。

## 自动化

最终全量 pytest：792 passed，1 条已有 pynvml 弃用警告，35.96 秒。含新增发布包排除测试。

完整 pytest 覆盖本地/云端、克隆/预设、取消/重复请求、音色模型绑定、过期采用、凭证脱敏、帧边界、旧 Local 类/媒体标签、Fal 路由。新增发布包测试确认不包含凭证文件、私有音频、模型环境。

Edge mock：Speech、Local、Cloud、Fal 的 380/460/560/720/900 宽度通过；node/host/root 分别 380/360/360、460/440/440、560/540/540、720/700/700、900/880/880。凭证六种来源组合、四类反馈及 @ picker 顶/中/底位置通过。

真实隔离 ComfyUI + Edge 也通过 Local 五档尺寸、历史与三个驱动选择的工作流保存/页面重载。脚本最初过早载入工作流，与 ComfyUI 启动自动恢复发生竞争；等待 networkidle 后原生产代码通过，临时生产改动已撤回。保留主程序初始化与缺少资源的 console 提示，pageerror 列表为空；不将其描述为浏览器完全零日志告警。

## 本地实机首轮

隔离 ComfyUI 运行在 127.0.0.1:8190，禁用 API 节点，仅加载 HuTX。使用已安装的 H3 INT8 ConvRot、Qwen3VL NVFP4/AWQ、视频/音频 VAE。本轮没有模型下载，没有真实 TTS、LLM、Fal、百炼或 OSS 请求。

复用此前人工试听通过的 5.4 秒、24kHz 本地 CosyVoice 输出。第三阶段历史生成耗时 19.414 秒，此值不是本轮重新测量。此前 Whisper 有同音误识，不能计作逐字匹配通过。

| 模式 | 设置 | 本轮队列耗时 | 结果 |
|---|---|---:|---|
| I2V | FL2VA + 本机 v1.2 Turbo LoRA，4 步 | 177.68 秒 | 执行/音轨通过；中途出现文字转场，画面未通过 |
| FL2V | 同一人物首尾帧 + FL2VA + v1.2 Turbo，4 步 | 174.77 秒 | 执行/音轨通过；出现多余图文，画面未通过 |
| Ref2VA | 人物参考图 + Ref2VA，无 LoRA，20 步 | 572.64 秒 | 执行/音轨通过；未保持持续正面口播，画面未通过 |

首轮工作流是 16:9/0.5MP，输出 960×544，人物竖图发生裁切。随后另存使用 adaptive 比例和明确固定人物镜头英文描述的复测，不覆盖首轮证据。模型执行成功不能代替视觉验收。

I2V/FL2V adaptive 复测分别用时 162.82/165.75 秒，人物完整入镜，六个采样画面可见口型变化，未再出现首轮图文转场。音轨前缀相关性仍为 0.998633，台词音频完整。抽帧检查不替代完整音画同步的人工验收。

Ref2VA adaptive 复测用时 590.30 秒，抽帧为持续正面人物特写，可见嘴部变化；六段成片（含首轮）音轨均通过同样检查。推荐验收文件为 i2va_portrait_00001_.mp4、fl2va_portrait_00001_.mp4、ref2va_portrait_00001_.mp4。首轮不佳样例完整保留。复测成功不抹去首轮失败，也不承诺任意 Prompt/Checkpoint 的口型效果。

使用时需要用户在 input 放置自己的图片、音频并按本机选择模型。CreateVideo 的 audio 必须使用 Adapter 的 mux_audio（第 6 个输出），不能误接 Decode 重新生成的音频。生产使用时可将 LoadAudio 替换为已采用的口播 AUDIO。

三段首轮成片均 158 帧/24fps，即 6.583 秒；5.4 秒音频没有截断。AAC 解码音轨长约 6.613 秒（编码帧填充），源音频前缀相关系数 0.998633。采样前 `lock_source_verified=true`；`verified_lip_sync=false` 始终保留。音轨相关性证明采用了正确声音，不证明嘴型同步。

本地报告和预览在开发目录 `.local-smoke-v040/`：各模式 `*-api.json`、`*-history.json`、`speech-results*.json`、`speech-media-verification.json`、`*-contact.png` 和 output/speech_acceptance/*.mp4。

## 待验收包

使用 tests/package_speech_candidate.py 生成 source-only ZIP，内附逐文件 SHA-256 清单、明确的待验收状态、当前插件版本及目标版本说明。重新读取 ZIP 校验每个文件并运行 ZIP 完整性检查。

排除 .speech-runtime、模型、缓存、测试产物、Git、环境变量文件、本机 DPAPI 凭证、个人音色和录音。额外检查常见嵌入式 Key/私钥模式；这不是对所有未知 secret 格式的绝对证明，凭证文件主要通过固定允许目录/类型排除。

此包不是一键包含模型的便携环境包。本机部署的 .speech-runtime junction 仍指向开发目录，不能移动或删除该环境。其他机器必须依据第三/四阶段安装说明另行准备环境、模型、用户音色及自己的凭证。工作流采用的音频需要同时保留对应 ComfyUI input/hutx-speech 文件。

## 发布边界

目前不升级正式 0.4.0、不覆盖发布正式版。用户的「稍后验收」不是通过。待持续人物画面、完整台词和嘴型验收通过后，才能完成计划中的正式升级与部署。云端真实计费验收另行授权；mock API 通过不等于真实云端账户/网络验收通过。

本轮改动仅为验收脚本、打包脚本、测试与记录；没有修改 GHVideoRequest、NormalizedVideoRequest、媒体标签、Fal 端点/价格/路由、输出顺序或 credential resolver。
