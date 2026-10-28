# Fused Turbo 二采音频隔离

同一 Fused Turbo 工作流的 A/B 实测确认：二采关闭时杂音消失；二采开启时，通用 `SamplerCustomAdvanced` 会再次采样 H3 的联合视频/音频 latent，因此不适合将二采后的音频直接解码。

测试工作流：[HuTX_v0.3.2_双引擎_二采保留首采音频.json](workflows/HuTX_v0.3.2_双引擎_二采保留首采音频.json)

如果画面没有可检测的人脸，`H3FaceTrackCrop` 会报错。可改用[跳过修脸的测试工作流](workflows/HuTX_v0.3.2_双引擎_二采保留首采音频_跳过修脸.json)：它保持 Fused Turbo 二采开启，只关闭人脸修复分支，先验证最终画面与首采音频。该分支的开关标题特意不含 `VOSR2`，避免双引擎前端按 Fused 默认值把它重新打开。原工作流仍保留 VOSR2 开启，用于有人脸的镜头。

接线：

1. 首采 `SamplerCustomAdvanced.output` 接入 `HuTX · 二采保留首采音频.first_pass_latent`。
2. 二采开关的输出接入 `selected_pass_latent`。
3. 该节点的 `av_latent` 接到原来的 `VRAMCleanup`，再接 `MiniMaxH3AVDecodeT8GH`。

二采开关打开时，保留二采画面和首采音频；关闭时，两路输入都是首采输出。VOSR2 仍只作用于解码后的画面。节点不会改动首采或二采的原始缓存张量，也不会删除已上传或已采用的音频。接入新节点后需重启 ComfyUI 再加载测试工作流。
