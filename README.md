# HuTX · MiniMax H3 Studio

**MiniMax H3 的 ComfyUI 一体化节点：云 / 本地视频生成、提示词优化、声音克隆与制作工作台。**

<p>
  <img alt="version" src="https://img.shields.io/badge/version-0.3.2.2-1E90FF?style=flat-square">
  <img alt="license" src="https://img.shields.io/badge/license-GPL--3.0--or--later-2ea44f?style=flat-square">
  <img alt="comfyui" src="https://img.shields.io/badge/ComfyUI-0.41.0-8A2BE2?style=flat-square">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20x64-0078D4?style=flat-square">
</p>

> **当前状态：v0.3.2.2 开发预览。** 功能可用，但 0.4.0 仍在等待画面/口型人工验收，云端真实计费链路尚未验收。请勿把「执行成功」当作「效果通过」。

[使用说明书](MANUAL.md) · [功能亮点](FEATURES.md) · [版本记录](CHANGELOG.md) · [技术文档](docs/)

---

## 为什么用它

- **一套节点覆盖三条路线**：Fal 云端（Max / Turbo）、本地 H3（5 合 1）、双引擎（Fused / HyperFlow），接线不用换。
- **提示词不再是纯文本**：官方标签可视化、素材 `@` 选择、本地/在线优化、历史对比，全部内嵌在节点里。
- **声音进同一条流水线**：本地 CosyVoice 或百炼云端克隆、20 种系统音色、A/B/C 多角色，采用后直接锁进视频。
- **从分镜到成片**：工作台保存镜头快照、逐段生成、断点续跑，最后按入点/出点和音量拼接导出 MP4。

---

## 功能亮点

| 能力 | 说明 |
|---|---|
| ☁️ 云端双变体 | `h3-max` / `h3-max-turbo` 同节点切换，`dry_run` 只计价不提交，成本护栏在提交前拦截 |
| 🖥️ 本地 5 合 1 | 主模型、CLIP、视频/音频 VAE、画幅、MP、时长一次选完，自动判定 T2VA / I2VA / L2VA / FL2VA / Ref2VA |
| 🔀 双引擎 | Fused Turbo 与 HyperFlow 共用素材与口播接口，切换引擎自动同步二采 / VOSR2 开关 |
| 🎵 二采保音 | 二采只换画面，音频继续用首采结果，避免重采样产生杂音 |
| ✍️ 提示词系统 | 官方标签渲染 + 缩略图、`@` 素材选择、四视图对比、优化历史 |
| 🧠 提示词优化 | 本地 Transformers / GGUF，或 RunningHub、OpenAI、Gemini、OpenRouter、百炼、SiliconFlow 等 8 类在线服务 |
| 🎙️ 声音克隆 | 本地 CosyVoice（离线）与百炼云端（20 种音色 / 11 种语言），参考声线与预设音色双路径 |
| 🎬 制作工作台 | 32 个镜头快照、逐段生成、成片裁剪与拼接、后台任务进度 |

完整清单见 [FEATURES.md](FEATURES.md)。

---

## 快速开始

```powershell
# 1. 放到 ComfyUI/custom_nodes/ 下，目录名必须是 HuTX-MiniMax-H3-Studio
#    不要同时保留旧目录，否则节点会重复注册

# 2. 安装依赖
..\..\python_embeded\python.exe -m pip install -r requirements.txt

# 3. 准备模型（见下表），重启 ComfyUI

# 4. 浏览器 Ctrl+F5 强制刷新

# 5. 可选：安装本地语音运行时
一键安装本地语音环境.cmd
```

### 模型目录

| 目录 | 用途 | 默认文件名 |
|---|---|---|
| `models/diffusion_models/` | 本地主模型 | `minimax_h3_fl2va_pruned_w4a8_mixed.safetensors` |
| `models/text_encoders/` | 文本编码器 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| `models/vae/` | 视频 / 音频 VAE | `minimax_h3_video_vae_fp16` / `minimax_h3_audio_vae_fp32` |
| `models/loras/` | HyperFlow 权重、Turbo LoRA | 用户自备 |
| `models/llm/` | 本地提示词优化 | 用户自备（可选） |

插件本身不下载任何模型。

---

## 节点一览

| 节点 | 类别 | 作用 |
|---|---|---|
| `HuTX · MiniMax H3 Local Studio` | Local | 旧主节点，生成 conditioning 与 AV latent |
| `HuTX · 本地视频输入 · 5合1` | Local | 本地路线入口，任务自动判定 |
| `HuTX · H3 双引擎视频输入 · Fused / HyperFlow` | Local | 双引擎入口，按需加载支路 |
| `HuTX · MiniMax H3 Adapter` | Utilities | 拆分 positive / av_latent / VAE / mux_audio / report |
| `HuTX · MiniMax H3 Dual Clock T8` | Local | 双时钟采样配置 |
| `HuTX · MiniMax H3 AV Decode T8` | Local | 联合音视频解码 |
| `HuTX · 二采保留首采音频` | Utilities | 二采换画面、音频用首采 |
| `HuTX Cloud Video Input · 5-in-1` | Cloud | 云端请求组装 |
| `HuTX · MiniMax H3 Max / Turbo` | Cloud | Fal 执行与成本护栏 |
| `HuTX · H3 HyperFlow · Compatibility Check` | HyperFlow | 架构与 LoRA 匹配检查 |
| `HuTX · H3 HyperFlow · 8-Step LoRA Patch` | HyperFlow | 应用 HyperFlow LoRA |
| `HuTX · H3 HyperFlow · 8-Step Dual Clock` | HyperFlow | 固定 8 步采样器 |
| `HuTX · 口播音频生成` | Speech | 单角色 TTS |
| `HuTX · 多角色口播` | Speech | A/B/C 三路 TTS |

---

## 三条路线

```text
# 云端
Cloud Video Input → MiniMax H3 Max / Turbo → SaveVideo

# 本地
本地视频输入 5合1 ─ model ───────→ (LoRA) → Dual Clock → SamplerCustomAdvanced
                  └ integration ─→ Adapter ─→ positive / av_latent / VAE
                                                       ↓
                              AV Decode → CreateVideo → SaveVideo

# 双引擎
H3 双引擎视频输入 → model / positive / av_latent / sampler / sigmas → 外部采样 → 二采 → AV Decode → 保存
```

示例工作流见 [`docs/workflows/`](docs/workflows/)。

---

## 系统要求

| 项目 | 要求 |
|---|---|
| ComfyUI | 支持 `comfy_api.latest` 的版本（实测 0.41.0） |
| 系统 | Windows 10/11 x64 |
| GPU | NVIDIA CUDA 显卡；RTX 4070 12 GB 可运行本地 H3 |
| 内存 | 建议 32 GB 以上 |
| 语音 | 独立运行时约 13 GB，可选安装 |

---

## 已知限制

- 0.4.0 未发布，等待口型/画面人工验收；
- 云端真实计费链路未验收，仅完成 mock 与离线签名验证；
- Continuation（续写）只预留上下文，尚未实现推理；
- 工作台只做硬切，无转场、字幕、多轨时间线；
- ComfyUI 单进程串行执行，本地并发上限为 1：20 条 15 秒视频约需 7–9.5 小时（RTX 4070 实测）；
- 本地语音运行时目前仅支持 Windows。

更多限制与排查见 [MANUAL.md](MANUAL.md)。

---

## 开发与测试

```powershell
# Python 回归（需要 pytest）
python -m pytest

# 前端单测
node --test tests/workbench_state.test.mjs
node --test tests/workbench_sequence.test.mjs
node --test tests/workbench_edit.test.mjs

# 浏览器测试（Playwright + Edge）
node tests/browser_workbench.mjs

# 生成纯源码发布包
python tools/package_plugin_code.py
```

测试不调用真实 TTS、LLM、Fal、百炼或 OSS；云端相关用例全部使用 mock 与测试凭证。

---

## 文档导航

| 文档 | 内容 |
|---|---|
| [MANUAL.md](MANUAL.md) | 完整使用说明书：安装、节点、提示词、音频、语音、工作台、排查 |
| [FEATURES.md](FEATURES.md) | 功能亮点与版本索引 |
| [CHANGELOG.md](CHANGELOG.md) | 版本记录 |
| [docs/](docs/) | 各版本设计与验收记录 |
| [docs/workflows/](docs/workflows/) | 可导入的示例工作流 |

---

## 许可与致谢

- 以 **GPL-3.0-or-later** 发布；
- 内置 T8 风格的条件构建与双时钟采样实现，致谢 [T8mars](https://github.com/T8mars/comfyui-minimax-h3-audio-T8)；
- HyperFlow 兼容桥接为独立实现，不包含上游源码与权重，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；
- 早期版本基于 [goohai/Goohai-MiniMax-H3_Integration](https://github.com/goohai/Goohai-MiniMax-H3_Integration) 演进。

## 免责声明

本项目与 MiniMax、阿里云百炼、fal 无隶属关系。

模型、API 与音色资源的使用受各自官方条款约束；云端调用会产生费用，请自行确认额度与授权。

## 作者

- GitHub：[hu675522](https://github.com/hu675522)
- B 站：[胡同学_168](https://space.bilibili.com/3707008517671681)
- Youtube：[胡同学_168](https://www.youtube.com/@%E8%83%A1%E5%90%8C%E5%AD%A6_168)
