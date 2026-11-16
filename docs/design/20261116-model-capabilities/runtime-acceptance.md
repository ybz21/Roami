# 模型选模运行验收

日期：2026-11-16。使用本任务私有实例 `/tmp/roami-model-implementation/instance`，启动与清理统一经过 `scripts/dev/isolated-roami.sh`；没有改动宿主模型设置。

## CLI 与真实推理链路

- `roami model list`：列出已接入模型与聚合池，展示能力声明与未知值。
- `roami model list --refresh --all --json`：从本机协议夹具读取上游目录，未接入条目保持 `configured=false`。
- `roami model list --capability image --json`：只保留声明支持图片的具体模型，不把聚合能力并集当作保证。
- `roami agent new --model free-pool --free-only`：实际创建独立对话并保存选择。
- `roami session new --kind roami --model mixed-pool --free-only --task ... --key model-selection-task --json`：原生任务执行成功；主执行请求落到免费成员 `fixture/free-text`，没有调用 `fixture/paid`。
- 用同一个幂等键与同一请求重试，返回完全相同的会话、任务与对话 ID。
- 调用记录中，独立的后台记忆工作仍使用保存的 Worker 默认模型；没有把单个任务的免费约束描述为整个节点费用承诺。

## 自动检查

待本轮最终检查完成后记录。

## 浏览器与手机

待最终构建与真实设备验证后记录。
