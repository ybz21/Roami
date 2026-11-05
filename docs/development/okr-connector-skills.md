# OKR 编写与 Connector Skill

权威入口为 [skills/okr-development/SKILL.md](../../skills/okr-development/SKILL.md)，
完整模板在其 assets/。先 cp -R assets/. 到空草稿，再按 parts/ 组合；
examples/ 是可调参考，不是通用模板入口。逐文件规则见 references/authoring.md。

项目根为工作目录，.roami/okr/ 保存目标、HTML/JSON看板、Connector Skill、
期望职责、指引和记忆。Connector 包在 connectors/<name>/，内部用 Python 或 MCP。
事实由受管操作校验并发布确认快照，最后原子更新 state/current.json；JSONL 是导出。
运行数据库保存任务、调度和重试，不另当指标主库。

模板不生成真实实例 ID、已成功状态或确认指针，也不把示例数值写成真实观测。
已有项目保留 Main、长期成员、来源历史和记忆。HTML 的只读 SDK、Connector 新包协议
与通用日更尚待接入；当前支持的 JSON widgets / GitHub / manual 继续作为兼容路径。

完整安装包由 package.files 校验；修改正文或资源后执行
python3 scripts/dev/okr-skill-manifest.py 更新清单。runtime 构建从这一份包生成资源，
不维护另一份正文。Docker 构建的 repository-root 命令见 agent-runtime 文档。
