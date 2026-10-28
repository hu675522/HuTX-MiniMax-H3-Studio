# HuTX H3 双引擎 Frontend 0.3.2

`GHLocalVideoInputDualEngineGH` 复用 Local Studio 的 Prompt、素材、Ref2VA 和口播桥接逻辑，但将引擎选择和透明采样输出集中到一个入口。

## 数据流

Fused 模式只创建：

`UNETLoader(Fused) → Chunk FFN（可选）→ SLA（可选）→ Integration → Adapter → DualClock`

HyperFlow 模式只创建：

`UNETLoader(Base) → Chunk FFN（可选）→ HyperFlow Patch → HyperFlow 8-Step Sampler`

HyperFlow 分支不会创建 Fused loader，也不会创建 SLA 或 Fused DualClock 节点。HyperFlow schedule 固定为 8 步。

两个分支都输出 MODEL、positive、AV latent、SAMPLER、SIGMAS、video/audio VAE。请在外部连接 `RandomNoise → BasicGuider → SamplerCustomAdvanced`，再连接 cleanup、`MiniMaxH3AVDecodeT8GH`、二采、VOSR2、CreateVideo 和 SaveVideo。

## 口播

`driver_audio` 保持主驱动音频语义；`reference_audio_1/2/3` 只作 Ref2VA 参考条件。引擎切换不会改变上游接线。成功锁定的口播同时从 `driver_audio_passthrough` 输出；没有主驱动音频时该输出为空。

## 二采与 VOSR2

二采继续接主采样输出 LATENT，并由外部开关执行真 bypass。VOSR2 继续接 AV Decode 的 frames，并在 Face Track/Crop、VOSR2、Stitch 后由外部开关选择原始帧或修复帧。四种原有 A/B 组合无需改动。

双引擎节点默认选中 Fused Turbo。切换引擎时，同一主链上标题包含“二采”及“VOSR2”的 `ComfySwitchNode` 会一起切换：Fused Turbo 为 ON，HyperFlow 为 OFF。只修改开关的布尔值，不改动任何接线；不在主链上或名称不匹配的开关保持原状。加载已保存工作流时按保存的引擎模式同步两个开关。

## Continuation 预留

可选输入 `continuation_latent`、`continuation_frames`、`continuation_audio` 当前只进入 `generation_context`，不会改变普通推理。上下文预留 previous AV latent、尾帧、尾音频、seed、overlap 和引擎/尺寸元数据，后续可接独立 Continuation Builder。

## 示例

[`dual-engine-hyperflow-ref2va-api.json`](workflows/dual-engine-hyperflow-ref2va-api.json) 是可直接导入 API prompt 的透明 HyperFlow 主链。将占位参考图片放入 ComfyUI `input`，并按本机模型文件名调整四个模型字段后执行。示例显式保留 RandomNoise、BasicGuider、SamplerCustomAdvanced、AV Decode、CreateVideo 和 SaveVideo。
