# 第二阶段：独立口播节点与 Mock UI

开发基线仍为 0.3.1。本阶段为开发预览，不升级正式版本、不部署。真实本地 TTS、云端声音 API、视频桥接分别属于后续阶段。

## 使用方式

新增节点 `GHSpeechInputGH`，显示为“HuTX · 口播音频生成（Mock 预览）”。

1. 选择本地 / 云端，以及参考声线 / 预设音色。
2. 参考声线方式填写 input 内参考 WAV 路径或上传本机 WAV；本地标准路径另填参考录音原文。节点可选 AUDIO 连接优先于参考文件，AUDIO 连接通过工作流执行，面板预览使用文件入口。
3. 新台词与参考原文分别保存。预设音色是按执行端绑定的测试音，不是正式人物音色。
4. 手动开启“明确开启 Mock 测试音模式”，点击生成，或 Queue 执行节点。不开启时拒绝生成，不会静默调用模型。
5. 试听、保存测试 WAV、采用当前结果。参数变化立即让面板旧结果失效；重新生成会改变 revision。音色示例通过浏览器产生短测试音，不发送生成请求。

Mock 输出是低音量正弦测试音，不读台词、不复制音色。不用于评估克隆质量，也不表示已实现数字人口播。

输出顺序：标准 AUDIO（float waveform [1, channels, samples] + sample_rate）、实际秒数、JSON speech_report。

## 数据与生命周期

- UI 仅写既定非敏感原生 widget 字段；音频结果 ID、运行状态、采用状态只在内存。不新增 node.properties、localStorage 或 sessionStorage。
- strict request whitelist 拒绝 API Key、credential reference 和未知 runtime 字段。服务没有凭证输入、没有网络客户端。
- 报告只有执行端、方式、Mock 模型版本、实际时长、elapsed 和 cache_hit；不带台词、参考录音内容或凭证。
- waveform PCM 内容哈希、采样率、声道、新台词、参考原文、执行端、音色、语速和 revision 组成缓存标识；文件名不作为音频身份。整数/浮点语速正规化。
- 进程内 LRU 最多 8 份结果，存活 30 分钟；不落盘。重启、过期或淘汰后需要重新生成；UI 的试听 URL 返回明确失效错误。
- 同参数重复运行复用缓存；生成中同参数服务端拒绝重复任务。前端取消后保留请求互斥直到原请求结束，拒收参数已变化的旧结果。
- 独立节点标准 AUDIO 可供其他音频工具使用；没有新增到现有视频链路的自动连接。

## 本机路由

`/hutx/minimax-h3/speech/catalog`、`/generate`、`/cancel`、`/audio/{audio_id}`，由 ComfyUI 提供常规 `/api` 兼容前缀。

Generate 只接受 request_id、parameters、reference_file。音频文件必须位于 ComfyUI input 内，Mock 阶段只接受 PCM16 WAV，限制参考时长及文件大小。不接受 URL 或任意外部路径。

## 验证

Python：四条 mock 分支、默认关闭、参数和凭证拒绝、音色绑定、内容缓存、预览/Queue 数字一致性、超时淘汰、取消/并发、路径穿越、异常脱敏、标准 AUDIO 输出、能力表及本机路由。

Edge fixture：`tests/browser_speech_stage_two.mjs` 使用真实 Edge DOM 和生产面板代码，拦截所有外部网络，仅 mock 本机 API。

| 节点宽度 | host | root | textarea | 横向溢出 |
|---:|---:|---:|---:|---|
| 380 | 360 | 360 | 340 | 无 |
| 460 | 440 | 440 | 420 | 无 |
| 560 | 540 | 540 | 520 | 无 |
| 720 | 700 | 700 | 680 | 无 |
| 900 | 880 | 880 | 860 | 无 |

截图与布局 JSON：`.test-artifacts/speech-stage2/`。同时测试成功、错误、取消、重复提交、参数变化、参考原文/新台词分离、序列化及单一计时状态。

全量 pytest：719 passed（比 686 基线新增 33 项），一个既有 pynvml 弃用警告。Edge fixture PASS，8 张截图与布局 JSON 已生成。没有执行真实 ComfyUI/H3 生成，此阶段验证的是独立 Mock 业务与浏览器布局。

队列回调只确认面板当前相同 audio_id 的预览，不把旧队列结果覆盖到用户已修改的参数上。没有面板预览时，Queue 的 AUDIO/时长/report 输出仍正常，面板试听需显式生成。

所有真实模型/API 下载、安装及付费调用均未执行。
