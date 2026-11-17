# 第一期验收记录

日期：2026-11-17。验收使用独立临时数据库和记录私有 socket 的测试实例；未部署本分支，未修改节点保存路由或当前 Main。

## 自动回归

`agent-runtime/tests/test_context_lifecycle.py` 与 `test_conversation_search.py` 覆盖近期完整回合、跨日整理、原文尾部、中文与失败/中断历史检索、已完成回合内中断尝试的整理、分页和字节上限、时区/DST、未索引来源保留、来源编辑/遗忘/删除、并发失效、失败退避、重启恢复、未完成任务要求与 revision 核对，以及日整理后无新消息的空闲补齐、活跃请求与较早请求延后完成的触发边界。

旧有历史读取、Main 简要投影、容量压缩及增量复用测试同时保留。新增迁移延续 SQLite 事务升级路径，Go 备份恢复兼容上限同步为 29。

新增的 35 项回归已通过。`scripts/dev/quality/check.sh full` 和提交钩子的 `quick` 均通过：每轮 Python 4,942 项通过、48 项跳过，另有 6 项子测试通过；Go 测试、i18n、hover、类型检查、密钥扫描与暂存文件检查通过，full 的前端生产构建通过。

旧迁移测试固定在 schema 28，继续校验原有事实；新增 schema 29 的事务回滚与稳定历史索引另有专项回归。涉及进程停止证据的 Go 测试使用独立 `tmux-spawn-*` 进程 scope，避免宿主并发进程干扰证据快照。对应 PR 的截图保留保存路由实测输出。

## 保存路由实测

使用节点已有 Main 路由、参数、能力与 Go 网关，隔离三组模拟历史：一次性三条报告、未完成发布准备中的“不要部署”、长期原文保留方案。新问题为无关的简单算术。

通过项：未决部署限制保留；一次性格式要求退出无关上下文；旧原文可检索；日归档可回源；原 Main 身份不变；保存路由摘要保持一致。实际时区为 `Asia/Shanghai`，来自该节点既有配置。

实际 Main `PromptBuilder` 装配的本地输入估算从 **7,772** 降至 **4,814 tokens**。对同一夹具数据库的只读备份，仅切换自动整理开关，调用真实 `runtime.loop.context.build`；系统说明、保存路由与工具目录一致，没有额外推理调用。一次性格式退出，未决部署限制继续保留。详情见 [main-assembly.json](main-assembly.json)。

保存路由脚本另测 `Context.project` 投影层，估算为 **13,067 → 4,172 tokens**；该层位于 Main 历史筛选之前，不能作为最终 Main 请求对比。两组数字均为模拟历史的本地估算，不是提供商实际用量或 CPU/内存指标。

首次实测发现中文单字重合导致无关格式片段召回；改为多字符词项匹配，并加入固定回归。输入估算的前后比较使用同一套系统说明、工具目录与模型配置，不把只减少正文或移除工具的差异算作优化。

可重复运行的入口（OUTPUT 必须为全新目录）：

```bash
scripts/dev/isolated-roami.sh /tmp/home-context-check \
  uv run --project agent-runtime --frozen python \
  agent-runtime/scripts/accept_context_lifecycle.py \
  --agent-config /path/to/node/agent.toml --data-root /path/to/node \
  --output /tmp/home-context-check/run-1
scripts/dev/isolated-roami.sh /tmp/home-context-check --stop
```

测试保存 `result.json` 和独立数据库。只使用模拟历史；路由只保存指纹，不输出密钥。此实测验证一组摘要提取和回源行为，不宣称通用语义准确率或生产性能结论。

稳定的实测结果摘要见 [acceptance.json](acceptance.json)。
