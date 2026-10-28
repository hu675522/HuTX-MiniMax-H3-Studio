# 示例工作流

这个目录用于存放可导入 ComfyUI 的示例与测试工作流。

> Git 无法跟踪空目录，因此保留这份 README 作为目录占位；新增工作流后可以直接删掉它。

## 两种格式

| 格式 | 特征 | 使用方式 |
|---|---|---|
| 界面工作流（graph） | 顶层包含 `nodes`、`links`、`last_node_id` | 拖入画布，或菜单 **Workflow → Open** |
| API 格式（prompt） | 节点 ID 到 `class_type` / `inputs` 的映射 | 通过 `/prompt` 接口提交，或由脚本调用 |

导入前请确认：

1. 工作流里引用的模型文件在本机 `ComfyUI/models/` 下存在；
2. 占位素材已放入 `ComfyUI/input/`；
3. 需要云端或语音能力时，凭证已在节点面板配置（不会随工作流保存）。

## 命名建议

```text
<版本>_<引擎或模式>_<用途>.json
例如：v0.3.2_dual-engine_hyperflow-ref2va-api.json
```

## 提交前检查

- 不包含本机绝对路径（`D:\...`、`/home/...`）；
- 不包含 API Key、Token、DPAPI 凭证文件；
- 不包含个人素材、用户音色或未授权的参考音频；
- 模型文件名尽量使用通用名，避免只有本机才有的私有文件。

## 相关文档

- [使用说明书](../MANUAL.md)
- [双引擎说明](../dual-engine-v0.3.2.md)
- [二采保留首采音频](../second-pass-audio.md)
- [HyperFlow Bridge](../hyperflow-bridge.md)
