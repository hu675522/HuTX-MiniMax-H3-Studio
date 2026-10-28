# 第三、四阶段补齐与部署说明

> 历史开发记录：部署目录现已使用独立的 `.speech-runtime`；跨电脑安装请参见 [一键安装与迁移](speech-runtime-installer.md)。

2026-09-12。仍为 0.3.1 开发预览，不代表第五阶段视频桥接已经完成。

## 第三阶段

- 用户本轮明确回复“试听通过”，声线与台词的人工验收已记录。
- 本地 Whisper base 离线转写已运行。原始结果是“很高興建到你今天我們一起測試本地聲音客龍”，包含繁体与同音误识，**不计作逐字匹配通过**。完整保存于 `.test-artifacts/speech-stage34/quality-acceptance.json`。人工试听通过与自动检查记录共同作为本次样例验收；不保证任意录音/台词无错字。
- 新增 DC/静音/低音量检查；本地 worker 使用固定 Silero ONNX 检测连续人声，再加载 CosyVoice。参考与生成音频通过检测；静音、440Hz 纯音被拒绝。VAD 是启发式质量检查，不保证背景音乐、噪声、多人声音一律识别正确。
- 新增 `speech_queue.py`：在 ComfyUI 初始化节点期间包装现有 queue.get/task_done。预览与已取出的工作流共用互斥门；后入队工作流等待预览子进程退出，入队和状态查询不被阻塞。queued TTS 在自身串行工作流内执行，不再次抢占该门。失败/取消释放门；未知队列接口拒绝本地预览，允许走工作流。
- 测试使用当前安装的 ComfyUI PromptQueue 类，验证两个竞争方向、异常释放和重复安装。无改动 ComfyUI 文件、H3 节点或视频合同。
- 加入 VAD 后再次实际离线生成成功（1.44 秒 WAV）；已验收的原 5.40 秒音频保留，没有覆盖。

新资源位于 `.speech-runtime/models/quality`：Whisper base 145,262,807 字节（仅验收工具使用）；Silero ONNX 2,327,524 字节（本地生成使用）。固定 URL 和 SHA256 见 `tools/download_speech_quality.py`。正常生成不下载资源。

## 第四阶段

删除原先未经证实的 DashScope `/uploads` / `oss://` 通用资源解析路径。CosyVoice 注册使用官方文档规定的可访问 URL；上传由用户自有北京地域 OSS 提供。

- 官方 OSS Python SDK 2.19.1、V4 签名，在隔离 Python 中执行。未安装到 ComfyUI embedded Python。
- 私有对象，随机 ASCII 文件名；GET 签名有效期 600 秒。上传 SDK 与百炼 API Key 相互隔离。
- 注册调用结束后在 finally 删除对象，包括注册失败、取消和上传结果不确定的场景。删除失败返回 `oss_cleanup`；**签名过期不等于对象被删除**。
- 为进程崩溃/机器断电兜底，用户应在专用 bucket 配置 `hutx-speech-temporary/` 前缀的一天过期生命周期。插件不会擅自修改 bucket 全局生命周期或已有对象。该规则未配置时，崩溃遗留对象需用户清理。
- 云端创建的音色 ID 与临时录音不同，不随录音删除；音色缓存仅本进程内，绑定账户/业务空间/模型/录音内容。音色失效时清除对应缓存，用户明确点击重新生成才重新注册，不自动重复付费请求。
- 独立固定错误码贯穿 provider→service→HTTP→UI，显示无权限、凭证无效、限流、超时、注册失败、音色失效、OSS 上传/清理和本地参考录音问题。任意 provider 正文不会进入 UI 或 report。
- 官方响应若提供 OSS HTTP 下载地址，升级为同 host HTTPS；下载不附带 API Key。

本阶段按计划完成 mock 验证。真实注册、合成、OSS 上传/删除均未调用，零云端计费；不将 mock 结果宣称为真实供应商验收。

## 使用云端克隆前的本机配置

系统预设音色只需要百炼语音 API Key。参考声线克隆还需要自有 **北京地域** OSS bucket 和具有该临时前缀 PutObject/GetObject/DeleteObject 权限的 RAM/STS 凭证。

在启动 ComfyUI 的进程环境中配置以下名称，不要填写到工作流、节点属性、Prompt 或源码：

| 环境变量 | 用途 |
|---|---|
| HUTX_SPEECH_OSS_BUCKET | 北京地域 bucket 名称 |
| HUTX_SPEECH_OSS_ACCESS_KEY_ID | OSS RAM/STS AccessKey ID |
| HUTX_SPEECH_OSS_ACCESS_KEY_SECRET | 对应 Secret |
| HUTX_SPEECH_OSS_SECURITY_TOKEN | 使用 STS 时的临时 token，可选 |

本轮没有读取或代填真实凭证。UI 仅显示 OSS 是否已配置，不返回任何环境变量值。上传子进程通过 stdin 接收凭证，命令行和临时文件不包含 Key；stdout 只供内部读取签名 URL/结果，stderr 丢弃。百炼语音 Key 仍独立使用原 env/session/DPAPI 边界，未修改 Fal/Optimizer resolver。

## 部署与运行

部署到 `D:\AI\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes\HuTX-MiniMax-H3-Studio`。

部署目录的 `.speech-runtime` junction 指向 `D:\PY\HuTX-MiniMax-H3-Studio\.speech-runtime`，包含新增 SDK/VAD。不能移动开发环境目录。复制完成后必须重启 ComfyUI，确保队列包装在 worker 启动前安装，再 Ctrl+F5 刷新前端。

旧锁源音频工作流保持原样；新的口播 AUDIO 尚未通过第五阶段桥接进入视频。未调用 Fal，未 commit/push。

## 主要变更

最终全量 pytest：758 passed，1 条已有 pynvml 弃用警告（38.30 秒）。本轮新增 19 项测试；Edge 380/460/560/720/900 均通过，细分错误码显示与不回显 provider secret 通过。12 个受保护视频/标签/凭证核心文件 SHA256 与稳定备份一致。官方 OSS SDK 离线 V4 签名检查通过（600 秒），未发送真实 OSS 请求。

新增：speech_errors.py、speech_queue.py、speech_quality.py、speech_oss.py、speech_oss_worker.py、tests/test_speech_completion.py、tools/download_speech_quality.py、tests/verify_speech_quality.py。

修改：speech_local.py、speech_worker.py、speech_service.py、speech_routes.py、speech_providers/bailian.py、speech_requirements.txt、web/js/speech_input.js、web/js/speech_controller.js、相关测试与状态文档。

## 官方依据

- CosyVoice 音色注册 URL：https://help.aliyun.com/zh/model-studio/voice-cloning-user-guide
- 注册/更新/删除接口：https://help.aliyun.com/en/model-studio/cosyvoice-clone-api-reference
- OSS SDK：https://github.com/aliyun/aliyun-oss-python-sdk
- Silero VAD：https://github.com/snakers4/silero-vad
- Whisper：https://github.com/openai/whisper
