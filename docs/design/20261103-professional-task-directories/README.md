# 专业执行器默认工作区隔离

关联 [issue #645](https://github.com/ybz21/Roami/issues/645)。此项是 [启动诊断 #640](https://github.com/ybz21/Roami/pull/640) 和 [工具输入简化 #644](https://github.com/ybz21/Roami/pull/644) 之后，针对用户再次提供的失败截图补查的工作区分配缺陷。

## Product Design

未指定目录的新专业任务使用稳定的每任务私有目录，与 Native 一致。一个遗留 writer 的结果未知，不应阻塞所有无关的默认任务。

用户明确指定目录、项目或已有会话时保持原选择；旧 writer 的保护保持有效。无需模型填写额外参数，也不新增 Main 工具。

## User Stories

1. 新建没有指定目录的 Claude/Codex/OpenCode/pi 任务，直接获得可写工作区。
2. 同一任务再次准备时复用该目录，保留已有文件；不同任务互不借用目录。
3. 用户指定的旧目录若仍有未确认 writer，继续拒绝写入并保留诊断，不能偷偷换目录。
4. 目录创建/可写性检查失败时，不启动执行器 CLI。

## 生产证据与失败链

[只读证据快照](evidence/production-sample.json)包括当前截图样本及两次早先失败的元数据；没有修改任务、终态或旧租约。

| 任务 | 创建时间（本地） | 准入后目录 | 结果 |
| --- | --- | --- | --- |
| 65291b93a72e418d87f13c8d3cdc9585 | 18:50:36 | /home/ai/.roami/workspaces/agent-coding | WORKSPACE_OUTCOME_UNKNOWN，-1 |
| f36abc9fe31e45748fee076bf3dfd468 | 20:33:42 | 同上 | 同上 |
| ad9adba6df574fac942a2c4d722f1424 | 22:04:59 | 同上 | 同上 |

三项 intent.target 都未指定 directory。第三项正是截图中的任务，约四秒后结束。三次执行都有 runner 的 started 标记，但均没有 prompt.txt、供应商 sessionBinding 或 agent_conversation_id，不能把 runner 启动当成 Claude 已接收任务。

目录的 writer.json 仍指向旧执行 `163d773b30abb90c977481b8a32878d6d6238f2dd271a070d2c7bc9e7d67ec80`，result.json 仍然缺失。该 writer 与 [此前报告](../20261103-workspace-launch-diagnostics/README.md) 相同。旧 Read hook 回调丢失的历史证据见此前报告；此次没有重新推断或伪造旧完成事件。

失败顺序为：专业任务未选目录 → Python 回退全局 coding_directory → Go 准备该目录并启动 runner → claimWorkspace 发现旧 writer 缺终态 → CLI 任务 exec 前失败。这里 -1 仍是启动前构造值，不是已观测到的 Claude 退出信号。

本次快照共 57 个任务、81 次尝试（[频次](evidence/frequency.json)）；确认 **3 次新专业任务启动失败受同一旧 writer 影响**，不把三次界面报错认作三次独立工具故障。其它 NATIVE_WORKSPACE_OUTCOME_UNKNOWN、真实工具未知、会话忙、模型认证等错误仍需分别归因，不能都用本次根因解释。

## Technical Design

- `agent-runtime/src/roami_agent/executors/roami_cli.py:154`：automatic_task_directory 为真时复用现有 prepare_task_directory；按 taskId 创建和复用目录，路径传给原 Go launcher，后续仍取得正常 workspaceId 和执行回执。
- 原代码在该分支直接回退 settings.coding_directory，导致全部默认任务共享目录。
- `agent-runtime/src/roami_agent/dispatch/routing.py:287`：移除专业任务必须具备共享默认目录的前置条件。路由选择不产生文件，执行器在启动前准备目录。
- `executors/task_directory.py`：仅更新说明；原有 0700、O_NOFOLLOW、可写性探测和稳定 taskId 逻辑复用。
- `agent.example.toml`：说明新任务默认私有目录，coding_directory 为旧 target 的兼容回退。

项目 worktree、明确目录、明确会话、既有续跑、模型、权限、预算和 Go writer 围栏均沿用现有路径。本修复不清空 pending、不删除 writer、不改旧 result，也不重放旧未知任务。

## 验证

### Python 契约回归

`tests/test_professional_task_directories.py` 覆盖四种专业执行器、有无 coding_directory 配置、不同任务隔离、同任务复用且保留文件、准备失败不启动 CLI、无需共享配置也能路由。

既有 `test_coding_executor.py` 增加明确目录保持原样的断言；项目/会话绑定及 Native 目录测试一起运行：

```bash
uv run --frozen --directory agent-runtime pytest -q tests/test_professional_task_directories.py tests/test_coding_executor.py tests/test_task_directories.py tests/test_routing_policy.py
```

结果：**89 passed**。full 质量门通过：Python **3,285 passed / 48 skipped**，Go、CLI 审计、ruff、i18n/hover/typecheck/build、秘密扫描均通过。quick 提交钩子同样通过：Python **3,285 passed / 48 skipped**；见 [检查记录](evidence/checks.txt)。

### 真实 Go CLI 与隔离 tmux 的协议验证

[实际回执](evidence/cli-isolation.json)来自本分支构建的 Go CLI、Python CodingExecutor 和由 `scripts/dev/isolated-roami.sh` 创建的私有 tmux。供应商执行器为假 Claude 脚本，没有调用真实模型；生成的三份最小 HTML 是夹具文件，不是用户原任务的交付物。

| 场景 | 结果 |
| --- | --- |
| 明确选择存在未知 writer 的旧目录 | failed，WORKSPACE_PRIOR_RESULT_MISSING，executionStarted=false，无输出文件 |
| 未指定目录的新任务一 | succeeded，在独立目录写出三份夹具文件 |
| 未指定目录的新任务二 | succeeded，在另一目录写出三份夹具文件 |
| 核对旧现场 | writer 字节未变；旧 result.json 仍缺失 |

验证只清理了所建私有 tmux 实例，使用同一隔离入口 --stop；没有使用或清理用户 tmux server。完整夹具执行脚本保留在本工作区 `tmp/workspace-directory-proof/verify.py`，命令及汇总纳入验收记录。

## 线上版本和未修复项

读取到的线上 CLI 版本为 `roami vokr-files-8b74b3bb`，二进制中没有此前 #640 引入的 WORKSPACE_PRIOR_RESULT_MISSING 标记；新生产结果也没有 executionStarted / failure 字段。最终复核时 CLI 已变为 `roami vokr-board-4d307a49`，诊断标记仍缺失；本次没有执行部署或覆盖检查期间的其它部署。新目录逻辑没有进行生产写入验收。

1. 本分支尚未部署，不能声称截图中的服务已恢复。
2. 三条历史失败不会被这次代码改写，旧 writer 未确认的停止边界继续保留；没有擅自恢复或重做原三份 HTML。
3. 明确要求使用旧目录的任务仍需要核对原执行的停止与结果证明。本修复只消除未选目录的新任务对该旧目录的依赖。
4. 当前是确定性协议/目录验收，没有重跑整个 RSI 实模基准，也没有把假 CLI 的成功当成真实 Claude 内容质量通过。
