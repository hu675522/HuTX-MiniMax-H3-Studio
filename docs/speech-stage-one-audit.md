# 第一阶段：视频音频能力审计与接入设计

完成日期：2026-09-11。本文件描述当前代码能力，不代表已经完成 TTS 或口型实机验收。

## 能力表

| 执行端 / 模型 | 模式 | 当前音频入口 | 原音频锁定 | 当前代码时长 | 新口播桥接 |
|---|---|---|---|---|---|
| Local / H3-Base-FL2VA 家族 | I2V | hybrid_audio，与首帧共同进入本地 conditioning | 有潜变量锁定代码；具体模型口型待验收 | 整秒 2～30，再向上对齐帧数 | 未开放 |
| Local / H3-Base-FL2VA 家族 | FL2V | hybrid_audio，与首尾帧共同进入本地 conditioning | 同上，不能推断官方保证支持 Hybrid | 同上 | 未开放 |
| Local / H3-Base-Ref2VA 家族 | Ref2VA | 参考视频声轨 / reference audio slots | 按 drive_audio_ordinal 选中一条音频锁定 | 同上 | 未开放 |
| Fal / H3 Max | I2V | 无；只发送 image_url | 无 | 整秒 5～15 | 不支持现有请求直接接入 |
| Fal / H3 Max | FL2V | 无；image_url + end_image_url | 无 | 整秒 5～15 | 不支持现有请求直接接入 |
| Fal / H3 Max | Ref2V | reference_audio_urls，且必须同时有图片或视频 | 当前 payload 没有锁原音频字段，只能确认音频参考 | 整秒 5～15 | 不能作为严格锁音频方案开放 |
| Fal / H3 Max Turbo | I2V / FL2V | 与 Max 的 keyframe payload 相同 | 无 | 整秒 5～15 | 不支持 |
| Fal / H3 Max Turbo | Ref2V | 模型注册表无此 endpoint | 无 | 不适用 | 不支持 |

未知或第三方融合 checkpoint 不从文件名推断能力。新功能在完成对应模型实测前不开放视频桥接。现有旧工作流不增加拦截、不改变路由。

## 代码依据

- `fal_models.py:H3_MODEL_REGISTRY`：Max / Max Turbo 实际 endpoint 注册，Turbo 没有 Ref2V。
- `fal_router.py:build_fal_plan`：显式拒绝 hybrid_audio；I2V/FL2V 只有首尾图；仅 Ref2V 添加 reference_audio_urls。
- `fal_router.py:_duration_seconds`：5～15 秒整秒。`validate_reference_shape` 拒绝纯音频参考。
- `local_video_nodes.py:define_schema/execute`：界面和参数校验 2～30 秒，固定 lock_source、denoise=0、drive ordinal=1；官方命名的 FL2VA / Ref2VA 家族任务不匹配会拒绝。
- `nodes.py:MiniMaxH3IntegrationGH.execute`：keyframe 从 hybrid_audio 取驱动音频；Ref2VA 按“未静音视频声轨在前、独立音频在后”排序。加入新口播时不能盲目假设第一个驱动源是 ref_audio_1。
- `conditioning.py:build_conditioning`：lock_source 使用 replace_audio_latent(..., 0.0)，不是仅在最后合并音轨。
- `nodes.py:_trim_audio_to_duration`：现有行为会截长补短。新链路必须在进入旧函数前检查完整音频长度，防止截掉台词；本阶段不改旧函数。
- `nodes.py:calculate_length`：round(seconds * 24)，再向上对齐到 17n+5。输入 5 秒得到 124 帧，约 5.1667 秒；输入 15 秒得到 362 帧，约 15.0833 秒。

## 官方模型边界与本地界面范围的区别

[MiniMax 官方模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3) 声明输出 4～15 秒、24fps；FL2VA 表列零至两张首尾图片，Ref2VA 支持图/视频/音频。参考音频单段 2～15 秒，总计不超过 15 秒。

因此，本地 UI 允许填 30 秒不等于官方保证支持 30 秒。15 秒帧数对齐又会略超 15 秒；第五阶段必须先确定目标模型的实际帧预算，再决定是否拒绝边界输入，不能自动截短音频。本次不把这项不确定性隐藏在“已支持”中。

## 确定的接入方案

本阶段新增独立 `GHSpeechInputGH`，输出固定为 AUDIO / FLOAT duration_seconds / STRING speech_report。原有 Cloud / Fal / Local 输出不变。

第五阶段优先给新 Local 输入节点增加可选的 `driver_audio` 接入，默认未连接保持原样；通过独立桥接辅助节点将 AUDIO 转为本机 input 下按内容寻址的 WAV，再交给成熟的文件音频入口。辅助节点负责完整时长检查、音频源选择、临时文件生命周期和冲突检测，不改旧 MiniMaxH3IntegrationGH 的 required inputs 或采样逻辑。

I2V/FL2V 使用 hybrid_audio；Ref2VA 必须明确选择新口播为 drive source，不能改变已有媒体编号，也不能默默覆盖已有独立音频或参考视频声轨。发生冲突则让用户明确选择。该桥接不在阶段二实现。

Fal 的严格锁音频链路保持禁用。不得自动把 I2V/FL2V 改成 Ref2V、不得新增 Fal 字段、不得用最终混音假装模型音频驱动。

## 第一阶段交付

- 本审计表与独立接入方案。
- `speech_capabilities.py` 提供 UI 可读的 9 行能力快照，所有新桥接均标为未开放并说明原因。
- 未修改媒体 contract、时长校验、Fal router/pricing、旧节点 schema 或凭证解析。
