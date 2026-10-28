# HuTX H3 HyperFlow Bridge

本项目内置 ZIP 提供的 HyperFlow Bridge v0.3 cleanup fix，并将三个节点接入现有 `ComfyExtension`：

- `HuTXH3HyperFlowCompatibility`：检查 H3 模型是否为标准 time embedder 架构。
- `HuTXH3HyperFlowPatch`：读取 `models/loras` 下带 HyperFlow metadata 的 safetensors，将 rank LoRA 和双时间嵌入 patch 到克隆模型。
- `HuTXH3HyperFlowSampler`：输出 HyperFlow 固定 8 步 sigma、双时钟 sampler 和 patch 后 MODEL。

## 推荐接线

```text
官方架构 MiniMax H3 MODEL
  → HuTX · H3 HyperFlow · Compatibility Check（先检查）
  → HuTX · H3 HyperFlow · 8-Step LoRA Patch
  → HuTX · H3 HyperFlow · 8-Step Dual Clock

HuTX Local Adapter 的 av_latent
  → HuTX · H3 HyperFlow · 8-Step Dual Clock
```

Patch 节点的 MODEL 输出继续连接 `BasicGuider`；Sampler 和 Sigmas 输出连接 `SamplerCustomAdvanced`。AV latent 同时连接 HyperFlow sampler 节点及采样节点的 latent 输入。

## 使用边界

- 权重放在 `ComfyUI/models/loras/`，插件不会下载权重。
- 首次质量验证使用官方架构 H3 base/ref2va checkpoint；不要叠加在 HuTX FusedTurbo 上进行基准判断。
- HyperFlow 是固定 8 步方案；sigma grid 优先读取 safetensors metadata，否则使用桥接器内置的 v1 默认网格。
- v0.3 将时间 LoRA 张量保存为普通 Python 属性，保留原 `time_embedder.proj_in/proj_out` 参数路径，避免 DynamicVRAM 清理时恢复不存在的合成 buffer 路径。
- Compatibility Check 只验证结构，不代表模型与权重的画质匹配已经通过。
- 这是本地采样扩展，不修改 GHVideoRequest、Fal、Cloud、口播和媒体标签协议。

## 来源

- HyperFlow: <https://github.com/Video-Rebirth/hyperflow>（Apache-2.0）
- ComfyUI: <https://github.com/Comfy-Org/ComfyUI>
- ZIP 原始桥接说明标记为 experimental；本项目保留这一状态。
