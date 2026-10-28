# 第三、四阶段开发验证

> 历史开发记录：文中关于部署目录使用 junction、不能移动开发目录的描述已过时。当前迁移方式请以 [一键安装与迁移](speech-runtime-installer.md) 为准。

以下是初次实现记录；后续补齐内容、官方 OSS 上传方式、人工验收和队列互斥请以 [2026-09-12 补齐说明](speech-stage34-completion-20260912.md) 为准。

开发目录：`D:\PY\HuTX-MiniMax-H3-Studio`。仍为 0.3.1 开发预览，随后已按用户要求部署，未 commit/push。第五阶段视频桥接尚未实现，旧原音频驱动路径不接入新的 TTS。

## 本地 CosyVoice

官方仓库与模型固定在 `speech_runtime_lock.json`。独立 Python 3.10.21、Torch 2.3.1+cu121、torchaudio 2.3.1+cu121，存放于 `.speech-runtime`。未修改 ComfyUI 的 Python 3.13 / Torch。仅启用常规推理；Windows ONNX tokenizer 使用 CPU，LLM/Flow 使用 CUDA。

模型 15 个文件共 5,427,041,134 字节，逐文件校验；另有约 13.6 MB WeText FST，固定提交及 SHA256 见 `tools/download_wetext_runtime.py`。Python 推理依赖见 `speech_requirements.txt`，构建约束见 `speech_build_constraints.txt`，实际环境冻结清单保存在 `.speech-runtime/environment-freeze.txt`。模型和运行环境不进入源码包。

实现调整：采用一次性子进程和临时文件 IPC，替代计划中的 loopback 服务，不开放监听端口。worker 禁止 socket 连接/DNS/发送，HF/Transformers 离线，WeText 绑定本地资源。启动前释放 Comfy 模型，完成/失败/取消后等待子进程退出，再删除临时录音和文本。预览在已有 Comfy 队列任务时拒绝启动；不要在预览期间另起 H3 任务，跨线程队列互斥仍留作第五阶段集成验收。

节点关闭 Mock，选本地/参考声线，提供 PCM16 WAV、准确参考原文和新台词。点击生成，试听后采用 AUDIO。可将自己的参考录音与原文保存为本机预设；没有随包分发第三方音色库。音色身份由 WAV 内容（含采样率/声道）与原文决定。

RTX 4070 实测：官方参考录音生成“很高兴见到你。今天我们一起测试本地声音克隆。”，得到 24kHz / 5.40 秒 PCM16 WAV，包含冷启动约 19.414 秒。显存前/后 906/915 MiB；另一次实际取消后 907 MiB，worker 已回收。该数据是整卡快照，含桌面占用，不代表模型峰值。记录与音频在 `.test-artifacts/speech-stage34/`。

退出条件尚待人工试听/转写确认声线相似度和中文准确性；不将 WAV 生成成功等同于质量验收。

部署目录为 `D:\AI\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes\HuTX-MiniMax-H3-Studio`。其中 `.speech-runtime` 使用 junction 连接开发目录的同名环境，不需要修改启动脚本；环境变量 `HUTX_SPEECH_RUNTIME` 仍可显式覆盖路径。暂不可移动或删除开发目录的运行环境。

## 百炼云端

北京地域；业务空间可选，克隆自动选择 CosyVoice v3.5 Plus，亦可选 v3.5 Flash；系统音色使用 v3 Flash，提供龙安洋、龙安欢。模型/声音 ID 不跨端、跨模型复用。HTTP 合成、下载、错误、取消与凭证全部以 mock 验证，零真实 API 调用。

语音凭证独立管理：`HUTX_SPEECH_DASHSCOPE_API_KEY`（兼容 `DASHSCOPE_API_KEY`） > 语音会话 > 语音 DPAPI 本机存储。文件在 ComfyUI user/default/HuTX-MiniMax-H3-Studio/speech_dashscope.dat。复用 Windows Current User 加密组件，但不修改原 Fal/Optimizer 凭证文件、格式或 resolver。UI 输入值仅出现在保存请求，立即清空；状态只返回布尔值和来源。

**尚待确认的集成边界**：官方 CosyVoice 注册文档示例使用音频 URL。当前克隆上传适配依据 DashScope SDK 通用 getPolicy/私有 OSS 上传及资源解析 header，mock 已覆盖，但尚未证明 voice-enrollment 接受该通用上传机制。不能宣称克隆上传已真实可用，也不能通过转发到第三方公开存储规避。下一步需官方确认或另行授权的真实服务验收；若不支持，需改用用户自有 OSS 的短期签名地址方案。当前没有上传任何用户录音。

不自动重试可能已计费的请求，不自动切换本地/云端。HTTP 取消只能停止客户端后续步骤，不能保证供应商已接收任务不再计费。服务商错误正文不回传、不记录，现阶段 UI 使用统一失败提示；细分错误码 UX 仍有提升空间。

## 验证与边界

最终全量 pytest：739 passed，1 条已有 pynvml 弃用警告（27.20 秒）。相对第二阶段 719 项增加 20 项适配器测试。12 个受保护视频/凭证核心文件与清理备份逐字节 SHA256 一致。

新增 `tests/test_speech_real_adapters.py` 覆盖凭证组合、实际 Windows DPAPI 重启式解密、注册模型与账户绑定、缓存、请求脱敏、worker 成功/失败/取消清理；离线 autouse fixture 阻止真实模型与云端传输。`tests/smoke_local_speech_runtime.py` 为显式本地实测工具，不属于 pytest。

Edge production panel/controller mock：380/460/560/720/900 节点宽度，对应 host/root 360/440/540/700/880，无横向溢出。覆盖取消、重复请求、过期结果、单一计时、凭证只发送一次、密码清空和模型选项禁用。截图位于 `.test-artifacts/speech-stage2/`。

未修改 GHVideoRequest、NormalizedVideoRequest、media labels、Fal router/endpoints/pricing 或旧节点输出顺序。不升级 0.4.0；待视频桥接及最终验收后再发布。

依据：
- https://github.com/FunAudioLLM/CosyVoice
- https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512
- https://help.aliyun.com/zh/model-studio/voice-cloning-user-guide
- https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide
- https://github.com/dashscope/dashscope-sdk-python/blob/main/dashscope/utils/oss_utils.py
