# HuTX · MiniMax H3 Studio 使用说明书

> 版本：**v0.3.2.2（开发预览）** · 最后更新：2026-10
> 适用环境：ComfyUI（实测 0.41.0）+ Windows x64 + NVIDIA GPU
> 相关文档：[功能亮点](FEATURES.md) · [版本记录](CHANGELOG.md) · [技术细节](docs/)

---

## 1. 这个插件是什么

把 MiniMax H3 的音视频生成封装成 ComfyUI 节点，并补齐从提示词到成片的工作流：

- **三种视频路线**：Fal 云端（Max / Turbo）、本地 H3（5 合 1）、双引擎（Fused / HyperFlow）；
- **提示词系统**：官方标签渲染、素材 `@` 选择、本地/在线优化、历史对比；
- **声音**：本地 CosyVoice 克隆与预设音色、百炼云端 20 种系统音色、A/B/C 多角色口播；
- **制作工作台**：分镜快照、逐段生成、成片裁剪与拼接导出。

插件不包含扩散模型权重，也不代替 ComfyUI 的采样器；模型需要用户自行准备。

---

## 2. 系统要求

| 项目 | 要求 |
|---|---|
| ComfyUI | 支持 `comfy_api.latest` 的版本（实测 0.41.0） |
| 操作系统 | Windows 10/11 x64（本地语音运行时目前仅 Windows） |
| GPU | NVIDIA CUDA 显卡；RTX 4070 12 GB 实测可运行本地 H3 |
| 内存 | 建议 32 GB 以上（模型大于显存时会占用系统内存做流式加载） |
| Python | 使用 ComfyUI 自带环境，另需安装 `requirements.txt` |
| 磁盘 | 本地语音运行时约 13 GB；模型权重另计 |

---

## 3. 安装

### 3.1 安装插件

```powershell
# 1. 复制到 custom_nodes（目录名必须为 HuTX-MiniMax-H3-Studio）
#    D:\ComfyUI\custom_nodes\HuTX-MiniMax-H3-Studio

# 2. 安装依赖（使用 ComfyUI 自带的 Python）
..\..\python_embeded\python.exe -m pip install -r requirements.txt

# 3. 重启 ComfyUI，然后 Ctrl+F5 强制刷新浏览器
```

> 不要同时保留旧目录（如 `Goohai-MiniMax-H3_Integration`），否则节点会重复注册。

### 3.2 可选：安装本地语音

双击插件目录下的 `一键安装本地语音环境.cmd`，或在 PowerShell 中执行 `Install-SpeechRuntime.ps1`。
它会下载独立的 Python 3.10、CosyVoice 源码与 `Fun-CosyVoice3-0.5B-2512` 模型，安装到 `.speech-runtime/`，不影响 ComfyUI 自己的环境。

详细迁移方式见 [一键安装与迁移](docs/speech-runtime-installer.md)。

### 3.3 升级

1. 备份当前 `custom_nodes/HuTX-MiniMax-H3-Studio`；
2. 用新版本覆盖（保留 `.speech-runtime`、`user/` 下的本机凭证）；
3. 重启 ComfyUI，再 Ctrl+F5。

---

## 4. 模型准备

文件放到 ComfyUI 对应目录，文件名可以不同，但要在节点里选对。

| 目录 | 用途 | 默认文件名 |
|---|---|---|
| `models/diffusion_models/` | 本地主模型 | `minimax_h3_fl2va_pruned_w4a8_mixed.safetensors` |
| `models/diffusion_models/` | 双引擎 Fused | `minimax_h3_fused_*.safetensors` |
| `models/diffusion_models/` | HyperFlow 基础模型 | 官方 H3 基础模型 |
| `models/text_encoders/` | 文本编码器 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| `models/vae/` | 视频 VAE | `minimax_h3_video_vae_fp16.safetensors` |
| `models/vae/` | 音频 VAE | `minimax_h3_audio_vae_fp32.safetensors` |
| `models/loras/` | HyperFlow 权重 / Turbo LoRA | 用户自备 |
| `models/llm/` | 本地提示词优化模型 | 用户自备（可选） |

本插件**不会自动下载模型**。

---

## 5. 三条视频路线

### 5.1 云端 Fal（最省事）

```text
HuTX Cloud Video Input · 5-in-1
        ↓
HuTX · MiniMax H3 Max / Turbo（execution_mode 先选 dry_run）
        ↓ video
SaveVideo
```

- 首次使用先在节点里配置 Fal Key（会话或本机 DPAPI 保存）；
- `dry_run` 只校验与计价，不产生费用；确认无误后改 `generate`；
- `max_estimated_cost` 是提交前的成本上限，超出会直接拒绝。

### 5.2 本地 5 合 1（单卡常用）

```text
HuTX · 本地视频输入 · 5合1
   ├─ model →（可选 LoRA / Adapter）
   ├─ integration → HuTX · MiniMax H3 Adapter
   │        ├─ positive → BasicGuider
   │        ├─ av_latent → SamplerCustomAdvanced 的 latent_image
   │        ├─ video_vae / audio_vae → AV Decode
   │        └─ mux_audio → CreateVideo.audio（原始音质）
   └─ local_report
```

推荐再接 `HuTX · MiniMax H3 Dual Clock T8` 生成采样器与 sigmas，然后：

```text
RandomNoise + BasicGuider + Dual Clock → SamplerCustomAdvanced → (二采) → AV Decode → CreateVideo → SaveVideo
```

### 5.3 双引擎（Fused / HyperFlow）

```text
HuTX · H3 双引擎视频输入 · Fused / HyperFlow
   ├─ model / positive / av_latent / sampler / sigmas
   ├─ video_vae / audio_vae
   ├─ driver_audio_passthrough
   └─ generation_context（预留）
```

- `engine_mode = fused_turbo`：Fused 模型 + Chunk FFN + SLA + DualClock；
- `engine_mode = hyperflow`：基础模型 + HyperFlow LoRA Patch + 8 步 Dual Clock，自动关闭 SLA 与二采；
- 切换引擎会同步切换主链上标题含「二采」「VOSR2」的开关，不会改接线。

可导入的 API 示例见 [双引擎 HyperFlow 示例](docs/workflows/dual-engine-hyperflow-ref2va-api.json)。

---

## 6. 节点参考

| 节点 | 类别 | 要点 |
|---|---|---|
| `HuTX · MiniMax H3 Local Studio` | Local | 旧主节点，兼容历史工作流；负责加载 CLIP/VAE 并生成 conditioning |
| `HuTX · MiniMax H3 Adapter` | Utilities | 把 bundle 拆成 positive / av_latent / VAE / mux_audio / report |
| `HuTX · MiniMax H3 Dual Clock T8` | Local | 双时钟采样配置，输出 model / sampler / sigmas |
| `HuTX · MiniMax H3 AV Decode T8` | Local | 联合解码 frames / generated_audio / video_latent / audio_latent |
| `HuTX · 本地视频输入 · 5合1` | Local | 模型、CLIP、VAE、画幅、MP、时长；任务自动判定 |
| `HuTX · H3 双引擎视频输入` | Local | Fused / HyperFlow 单入口 |
| `HuTX · 二采保留首采音频` | Utilities | 二采换画面、音频用首采 |
| `HuTX Cloud Video Input · 5-in-1` | Cloud | 云端素材与请求组装 |
| `HuTX · MiniMax H3 Max / Turbo` | Cloud | Fal 执行，dry_run / generate，成本护栏 |
| `HuTX · H3 HyperFlow · Compatibility Check` | HyperFlow | 检查模型架构与 LoRA 是否匹配 |
| `HuTX · H3 HyperFlow · 8-Step LoRA Patch` | HyperFlow | 打 HyperFlow LoRA |
| `HuTX · H3 HyperFlow · 8-Step Dual Clock` | HyperFlow | 固定 8 步采样器 |
| `HuTX · 口播音频生成` | Speech | 单角色 TTS，输出 AUDIO / duration / report |
| `HuTX · 多角色口播` | Speech | A/B/C 三路 AUDIO |

---

## 7. 素材与提示词

### 7.1 任务判定

| 输入组合 | 任务 | 标签格式 |
|---|---|---|
| 无图 | T2VA | 无图片标签 |
| 首帧 | I2VA | `<Picture 1>` |
| 尾帧 | L2VA | `<Picture 1>` |
| 首帧 + 尾帧 | FL2VA | `Picture 1`、`Picture 2`（不带尖括号） |
| 参考图 / 视频 / 音频 | Ref2VA | `<Picture N>`、`<Video N>`、`<Audio N>` |
| 首尾帧 + hybrid_audio | Hybrid | `<Picture 1>` + 参考音频 |

### 7.2 素材上限

- 参考图片最多 **9 张**；
- 参考视频最多 **3 个**；
- 独立参考音频最多 **3 个**；
- 视频自带音轨会被计入音频序号，可在卡片右上角静音。

### 7.3 标签规则

- 单击素材插入标签，双击视频插入其音轨音频标签；
- 素材排序、增删后编号自动重排；
- 「严格提示词标签」开启时，引用不存在的编号会在执行前报错；
- 支持中文别名：`图像1`、`图1`、`视频1`、`音频1` 等。

### 7.4 画幅与尺寸

- `adaptive` 会跟随当前模式第一个有效视觉素材的宽高比，没有素材时用 16:9；
- 输出尺寸自动对齐 32 像素；
- 参考素材尺寸策略：匹配目标像素 / 1.2× / 1.5× / 2× / 最大值，只缩小不放大。

---

## 8. 音频

### 8.1 四种音频模式

| 模式 | 行为 |
|---|---|
| `native` 自动生成 | 不使用驱动音频，模型生成目标音频 |
| `reference_only` 仅参考 | 音频只作参考条件，模型生成新音频 |
| `lock_source` 原声输出 | 驱动音频写入 latent，保持源音频，并单独输出同音质音轨 |
| `remix_source` 重混 | 以驱动音频为基础重绘，强度可调 |

没有可用驱动音频时自动回退到 `native`。

### 8.2 裁剪与对齐

- 裁剪界面只保存起止时间，不修改原文件；
- 支持拖动边界、整体移动、滚轮缩放、中键平移、选区播放；
- 可一键同步到视频目标时长；
- 执行时按保存区间读取，超出截断、不足补静音。

### 8.3 解码与接线

- `mux_audio` 是原始音质音频，必须接到 `CreateVideo.audio` 或 `VHS_VideoCombine.audio`；
- 不要误接 AV Decode 重新生成的音频（会二次有损）；
- 解码后若检测到开头短促异常波形，会自动静音该片段并淡入。

### 8.4 口型说明

`lock_source_verified=true` 只证明采用了正确的声音，**不证明嘴型同步**。口型效果取决于模型、步数、Prompt 与画面构图，需要人工验收。

---

## 9. 声音克隆与口播

### 9.1 选择执行端

- **本地**：CosyVoice，免费、离线、需要 `.speech-runtime`；
- **云端**：百炼北京地域，按量计费，需要 API Key；克隆还需要自有 OSS。

### 9.2 本地

- 模式：预设音色 / 参考声线克隆；
- 克隆需要参考音频 + 参考原文（可自动识别，需 Whisper 质量模型）；
- 生成前做人声检测，静音与纯音会被拒绝；
- 与 ComfyUI 队列互斥，TTS 结束自动回收进程与显存。

### 9.3 云端

| 环境变量 | 用途 |
|---|---|
| `DASHSCOPE_API_KEY` 或界面保存 | 百炼语音 API Key |
| `HUTX_SPEECH_OSS_BUCKET` | 北京地域 bucket |
| `HUTX_SPEECH_OSS_ACCESS_KEY_ID` | OSS AccessKey ID |
| `HUTX_SPEECH_OSS_ACCESS_KEY_SECRET` | OSS Secret |
| `HUTX_SPEECH_OSS_SECURITY_TOKEN` | STS 临时 token（可选） |

- 克隆上传使用签名 URL（600 秒），注册结束即删除对象；
- 建议给 bucket 配置 `hutx-speech-temporary/` 前缀的一天过期生命周期；
- 凭证不写入工作流、日志或报告。

### 9.4 使用流程

1. 选择执行端 → 选音色或上传参考音频；
2. 输入新台词 → 生成 → 试听；
3. 满意后点「采用」，音频被冻结为该镜头的口播；
4. 接 `driver_audio`，或让工作台自动连线；
5. 生成视频时按真实时长与帧网格对齐，越限直接报错。

---

## 10. 制作工作台

### 10.1 入口

ComfyUI 侧栏 **HuTX总台**，顶部「展开」进入大工作区。

### 10.2 三个页面

- **角色与声音**：选择或新建单人/多角色口播，生成、试听、采用、连到镜头三槽；
- **镜头生成**：保存镜头快照（提示词、时长、引擎、素材、口播、种子、开关），逐段生成；
- **成片管理**：从最近 50 条历史中筛选 HuTX 视频，预览、下载、重新生成、拼接导出。

### 10.3 镜头与批量

- 最多 32 个镜头；
- 「逐段生成未完成镜头」串行提交，每段独立任务 ID；
- 「停止后续镜头」只停后续，不打断当前任务；
- 网络中断保留任务编号，再次继续优先核对原任务；
- 修改提示词或时长后，镜头回到待生成。

### 10.4 拼接导出

- 1–32 段，累计 ≤10 分钟，单段 ≤120 秒，最高 4096×2160；
- 只支持相同分辨率，不自动拉伸；
- 每段可设入点/出点、0–200% 音量、静音；
- 统一 24fps H.264 + 48kHz 双声道 AAC；
- 后台执行、可取消，输出到 `ComfyUI/output/video/HuTX_Workbench/`。

### 10.5 保存

项目、镜头、任务、片段清单保存在当前工作流的 `extra.hutx_workbench`（schema 3，兼容 1/2）。**关闭前请保存工作流**。

---

## 11. 提示词优化器

### 11.1 供应商

| 类型 | 支持 |
|---|---|
| 本地 | Transformers 视觉语言模型、GGUF（含 mmproj） |
| 在线 | RunningHub 国内/海外、OpenAI Chat、OpenAI Responses、Gemini、OpenRouter、百炼、SiliconFlow、自定义兼容接口 |

### 11.2 凭证优先级

`环境变量 → 有效会话凭证 → 本机 DPAPI 密文`

- 路径：`ComfyUI/user/default/HuTX-MiniMax-H3-Studio/prompt_optimizer_credentials/<provider>.dat`
- 删除本机密文不会影响环境变量与会话；
- 界面显示「已配置」只代表保存成功，不代表调用权限或余额。

### 11.3 输出控制

- 最大输出 Tokens：默认 4096，范围 512–8192；
- 本地优化会先卸载当前显存中的模型，完成后再卸载语言模型；
- 自动优化最长等待 200 秒，失败或超时回退原始提示词。

---

## 12. 保存、迁移与兼容

- 工作流保存：提示词、素材、模式、裁剪、静音、驱动音频、优化器配置、工作台项目；
- 旧工作流：GH 节点 ID 与状态字段保持兼容，可直接打开；
- 迁移到另一台机器需要：插件代码、模型权重、`input/` 素材、已采用的口播文件、本机凭证（重新输入）；
- `.speech-runtime` 体积大，不建议随代码包分发。

---

## 13. 性能与批量

### 13.1 实测基线（RTX 4070 12 GB）

| 项目 | 数值 |
|---|---|
| H3 主模型 | 约 19,995 MB（大于显存，动态流式加载） |
| 文本编码器 | 约 14,955 MB |
| 单条 15 秒视频 | 约 20–28 分钟（含二采与修脸） |
| 20 条 15 秒视频 | 约 7–9.5 小时 |

### 13.2 并发结论

ComfyUI 单进程单 worker 串行执行；显存小于模型，**单卡并行只会互相抢占，不会更快**。

- 本地并发度固定为 1；
- 需要更快只能：降分辨率/步数、关闭二采与修脸做初稿、开多卡/多机、或改用云端；
- 批量任务建议夜间执行，并依赖工作台的任务编号做断点续跑。

### 13.3 提速建议

1. 批量前先统一优化提示词，避免生成阶段触发本地 LLM；
2. 批量前先生成并采用全部口播，避免 TTS 与视频抢显存；
3. 初稿关闭二采与 VOSR2，挑片后再单独精修；
4. 不要开启 `--highvram`（模型大于显存，收益为负）。

---

## 14. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 节点菜单里找不到插件 | 未重启或目录名不对 | 确认目录名，重启 ComfyUI，Ctrl+F5 |
| `Ref2VA requires the Ref2VA checkpoint` | 模型与任务不匹配 | 切到对应 checkpoint |
| `当前提示词引用了不存在的素材标签` | 严格标签开启且编号失效 | 修正标签或关闭严格模式 |
| 显存不足 / 驱动重置 | 单卡超载或同时跑两个任务 | 降低分辨率/时长，确保并发为 1 |
| 提示词优化 401/403 | Key 无效或无权限 | 重新配置凭证或换模型 |
| 云端音色「音色失效」 | voice ID 过期 | 明确点击重新生成（会重新计费） |
| OSS 上传失败 | 地域/bucket/权限不对 | 检查北京地域与 PutObject 权限 |
| 本地 TTS 报环境缺失 | `.speech-runtime` 不完整 | 重新运行安装脚本 |
| 拼接失败 | 分辨率不一致或磁盘不足 | 统一分辨率，检查输出目录空间 |
| 工作台任务一直「跟踪」 | 队列已结束但历史未写入 | 等待或检查 `/history`，不要重复提交 |

---

## 15. 已知限制与验收状态

- **0.4.0 未发布**：等待人工画面/口型验收；
- **云端真实计费链路**未验收（本地仅 mock 与离线签名验证）；
- **Continuation**（续写）只预留上下文，尚未实现推理；
- 工作台只做硬切，无转场、字幕、多轨时间线；
- 本地并发上限 1，20 条 15 秒视频约需 7–9.5 小时；
- 本地语音运行时仅支持 Windows。

---

## 16. 许可与致谢

- 本插件以 **GPL-3.0-or-later** 发布；
- 内置 T8 风格的条件构建与双时钟采样实现，致谢 [T8mars](https://github.com/T8mars/comfyui-minimax-h3-audio-T8)；
- HyperFlow 兼容桥接为独立实现，不包含上游源码与权重；
- 早期版本基于 [goohai/Goohai-MiniMax-H3_Integration](https://github.com/goohai/Goohai-MiniMax-H3_Integration) 演进；
- 与 MiniMax、阿里云百炼、fal 无隶属关系，模型与接口以其官方条款为准。
