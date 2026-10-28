# 本地 CosyVoice 一键安装与迁移

插件代码与本地语音推理环境分别分发。安装器只写当前插件目录的 `.speech-runtime`，不修改 ComfyUI 自带 Python、H3 模型目录或用户 API 凭证。仅支持 Windows x64；在线安装需要可访问 GitHub、PyTorch、Hugging Face／ModelScope 和 Python 软件包源，并预留约 20 GB 空间。CosyVoice 使用 NVIDIA CUDA 推理；显卡驱动与系统运行库仍由目标电脑提供。

## 新电脑在线安装

1. 将插件代码包 `HuTX-MiniMax-H3-Studio-v0.3.2.2-code.zip` 解压到 ComfyUI 的 `custom_nodes`；解压后应出现 `HuTX-MiniMax-H3-Studio` 文件夹。
2. 双击根目录的 `一键安装本地语音环境.cmd`。没有本地运行包时，默认按 `speech_runtime_lock.json` 的固定版本在线安装。安装过程较长，失败后可重试，已校验下载会复用。
3. 看见“本地 CosyVoice 运行环境检查通过”后重启 ComfyUI。

安装器准备独立 Python 3.10.21、Torch/Torchaudio 2.3.1+cu121、固定版本 CosyVoice/Matcha 代码、模型、WeText 和参考录音自动转写所需模型。完成后校验关键文件及 Python 包导入；默认清理安装缓存。可用 `-KeepCache` 保留下载缓存，供调试或离线重装。

## 无网络或多台电脑复用

在一台已安装并可用的电脑上，进入插件目录运行：

```powershell
.\Install-SpeechRuntime.ps1 -Mode Pack -OutputPath D:\HuTX-CosyVoice-Runtime.zip
```

生成包不包含 uv 安装缓存、Torch 下载包、个人音色或 API 凭证。将 ZIP、同名 `.sha256` 校验文件与插件代码一同复制到目标电脑，并将 ZIP 命名为插件根目录下的 `HuTX-CosyVoice-Runtime.zip`；双击同一个 CMD 文件即可自动从包安装。也可指定包路径：

```powershell
.\Install-SpeechRuntime.ps1 -Mode Bundle -BundlePath E:\HuTX-CosyVoice-Runtime.zip
```

代码包可在开发目录执行 `python tools/package_plugin_code.py` 重新制作，输出在 `.test-artifacts/runtime-packages`。它排除本机运行环境、缓存和测试产物。

安装器会校验版本、解压到临时目录，再修复虚拟环境中的 Python 路径。目标电脑已存在 `.speech-runtime` 时不会覆盖；可先运行 `-Mode Check` 检查。运行包 ZIP 很大，复制时需留足目标盘空间。包不含用户保存的声音；这些数据位于 ComfyUI 的用户目录，需要用户另行迁移。

```powershell
.\Install-SpeechRuntime.ps1 -Mode Check
```

当前安装器不安装 H3 视频模型或 HyperFlow 权重；这些模型仍由 ComfyUI 自己的模型目录管理。打包发布插件源码时，应排除 `.speech-runtime`、`.test-artifacts` 和本机凭证。若导入 Torch 时报 DLL 错误，请先检查显卡驱动及 Microsoft Visual C++ 运行库。
