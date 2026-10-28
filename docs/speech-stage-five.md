# 第五阶段：口播 AUDIO 与本地视频集成

2026-09-12。开发目录已实现第五阶段；版本仍为 0.3.1 开发预览。正式升级、打包部署及真实 H3 口型同步验收属于第六阶段。本轮没有运行真实 TTS、Fal、LLM 或 H3 采样。

## 使用方式

1. 在「口播音频生成」选择本地/云端、克隆/预设，填写新台词，生成并试听。
2. 点击「采用此音频」。生成结果写入 ComfyUI input/hutx-speech/adopted，工作流仅保留相对文件路径。重开工作流会提示执行时校验已采用文件。
3. 将 audio 输出连接「本地视频输入 · 5合1」的可选 driver_audio。
4. 展开「连接口播 AUDIO（可选）」，明确确认 FL2VA 或 Ref2VA 主模型家族。第三方文件名不作为能力证明；确认的家族必须与画面模式匹配。
5. I2V/FL2V 使用 hybrid_audio；Ref2VA 使用独立 ref_audio 槽位。有旧音频或未静音的视频声轨时，默认拒绝冲突，需要明确选择「使用连接口播作为驱动」。
6. 沿用原有 Local integration → Adapter → Sampler → Decode 链。已有视频流程没有连接 driver_audio 时保持原行为。

用户明确截取片段时，可在 AUDIO 连线上加入 ComfyUI 的 TrimAudioDuration；桥接检查裁剪后的实际采样数。不会自动裁剪、变速或改写台词。

## 时长和音频选择

- 以实际 samples/sample_rate 计算时长。拒绝空波形、非法采样率、NaN/Inf、超范围幅度，支持单批次单/双声道 AUDIO。
- H3 采用 24 fps、17n+5 帧对齐。现有整数秒接口的 15 秒会得到 362 帧，超过 15 秒；新桥接最多使用 14 秒设置对应的 345 帧，即 14.375 秒。14.99、15.00、15.01 秒均被拒绝，不截断新台词。用户明确设置 15 秒及以上同样拒绝，不擅自降低设置。
- 在不缩短用户视频设置的前提下，向上找覆盖完整口播的帧预算；例如 5.4 秒音频选择 6 秒设置。短音频沿用原逻辑补齐尾部静音。
- Ref2VA 保留原有媒体槽位、Prompt 和 canonical tags，不依据文件名识别音频。自动追加到最后一个独立音频槽位之后；不填前方空洞而改变既有编号。槽位已满时需明确选择替换。
- Local 的音频序号先计入未静音且实际包含音频的视频，再计入独立音频。视频声轨 + 旧独立音频 + 新口播时，驱动序号为 3，标签为 `<Audio 3>`。
- 沿用旧逻辑将独立参考音频补齐到输出时长，因此额外检查独立音频累计 15 秒和混合素材 12 个上限。此检查没有修改旧的媒体协议。
- conditioning 完成后再次比对被锁定音频与新口播文件的采样率、声道、完整波形前缀和帧数；不一致就阻止采样。报告区分 `lock_source_verified` 与仍为 false 的 `verified_lip_sync`。波形锁定通过不等于真实口型同步验收通过。
- Fal 没有开放新的 AUDIO 桥接，端点、价格、路由和输出顺序不变。

模型范围依据：[MiniMax H3 官方模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3)。14.375 秒是本项目整数秒及帧对齐接口推导的保守上限，不是修改官方 15 秒范围。

## 采用快照和安全

POST `/api/hutx/minimax-h3/speech/adopt` 仅接收 audio_id，返回 adopted_audio_file。采用文件由后端原子写入；WAV 和 JSON 清单均以内容 SHA-256 命名。清单仅包含 schema、参数指纹、音频路径和公开报告，不保存凭证或原始参考/新台词文本。

工作流重试或服务重启后，口播节点直接加载采用文件，校验参数指纹及文件哈希。文件丢失、损坏、参数不匹配时明确失败，绝不回退到自动 TTS 请求。修改 UI 参数或点击生成/重生成会清除旧采用引用；改变参数后须重新生成试听。

桥接文件位于 ComfyUI input/hutx-speech/driver，采用文件位于 input/hutx-speech/adopted。失败不删除文件，没有自动过期清理；用户迁移工作流需同时复制相关 input 文件。仅在确认无工作流引用后手动清理，避免视频重试失去音频。

既有 Prompt Optimizer、Fal 和语音凭证 resolver、加密格式不变。没有新凭证字段进入 workflow、state 或报告。

## 验证与改动

最终全量 pytest：791 passed，1 条已有 pynvml 弃用警告，37.87 秒。相对第三/四阶段 758 项基线新增 33 项。

fal_router.py、fal_credentials.py、fal_api_client.py、fal_models.py、fal_h3_max.py、gh_video_request.py、local_video_state.py、prompt_optimizer.py 的 SHA-256 与清理后的稳定备份一致；四个旧 Local 类的 AST 回归通过。新增控件使用现有深色样式，样式调整后 Edge 布局再次通过。

新增 tests/test_speech_bridge.py：33 项覆盖精确帧预算、边界拒绝、I2V/FL2V/Ref2VA、冲突显式选择、静音视频、稀疏槽位、原始 state 不变、旧执行器真实选择链、采样前错误源阻断、采用路由、缓存过期/重启式复用、参数变化/篡改拒绝、主动裁剪及不重复调用 TTS。

Edge mock 执行生产 JS，覆盖采用、重开、失效状态、控件保存和五档宽度。Local / Cloud / Speech 的 node→host→root 分别为 380→360→360、460→440→440、560→540→540、720→700→700、900→880→880，均无水平溢出；Local/Cloud 的 @ picker 顶/中/底位置检查通过。

源文件：新增 speech_bridge.py、speech_snapshot.py；修改 local_video_nodes.py、speech_nodes.py、speech_service.py、speech_routes.py、speech_capabilities.py、web/js/gh_local_video_input.js、web/js/speech_input.js、web/js/speech_controller.js。

测试文件：新增 tests/test_speech_bridge.py；修改 tests/test_local_video_core.py、tests/test_speech_stage_two.py、tests/browser_speech_stage_two.mjs、tests/browser_local_shared_ux_fixture.mjs。
