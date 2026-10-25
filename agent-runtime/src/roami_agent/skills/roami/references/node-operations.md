# 节点、登录、插件与运维

这里是专业 Agent / 运维终端操作手册，不是自动扩张 Main 工具权限。用户仅要求查资料、发消息或看进度，不需要顺带改服务配置、升级依赖或迁移数据库。

## 命令入口

| 命令族 | 用途 | 帮助 |
| --- | --- | --- |
| project | 项目与完整会话归属 | `roami project help` |
| session | tmux 会话 / 窗格 / 蜂群 | `roami session help` |
| chrome | 浏览器、截图、录屏 | `roami chrome help` |
| agent | Main、任务、提醒、回报、资源 | `roami agent help`，子命令 help |
| auth | 当前节点 Web 登录 | `roami auth help` |
| plugin | 节点插件、命令、审计 | `roami plugin help` |
| db | 状态、迁移、备份和恢复 | `roami db help` |
| server | Go Web 服务 | `roami server --help` |
| help / version / completion | 总览、版本与补全 | `roami help`、`roami version` |

project/auth 的 --server URL 或 ROAMI_SERVER 选择服务，不把别的节点会话当本机。chrome 的 --cdp 选择浏览器实例；agent 使用当前节点私有 Unix socket，不能以 project --server 推断它也切换了 Agent 服务。认证由 Go 统一入口负责。

## 登录和诊断

与项目文件无关、已获用户授权的本机操作，Main 直接调用 `bash`，设置 `scope:"host"`，不传 `cwd`。
例如 `{"argv":["df","-h"],"scope":"host"}`；同一入口支持系统命令和脚本，不需要为每类查询添加工具。
命令运行在当前 Agent 节点的临时工作目录，结束即删除；这是通用本机执行，不是只读沙箱，不限制绝对路径访问。
遵守用户授权，不用它绕过任务工作区、禁用能力或受管资源协议。通用命令保守记录为 write，不按命令名猜测只读。
项目文件任务保留原目录与执行器；需保留的产物使用原工作区。resourceOnly 仍仅限浏览器导航与观察。

`roami agent host processes --input '{"limit":10}'` 保留为可选结构化只读快照，不承担通用本机路由。
它只返回进程名称和资源指标；CPU 为 ps 生命周期平均值，100% 代表一个核；Linux 内存／swap 来自 /proc，未知值为 null。

```bash
roami version
roami auth status --json
roami agent status
roami plugin status
roami db status --json
```

auth login 为交互隐藏密码，自动化用 `roami auth login --stdin --json` 从私有 stdin 读 password/code JSON，避免把口令放进 argv / Shell 历史；不读取或回显凭据文件。auth logout 会使现有认证失效，仅在用户要求退出时执行。401 / ROAMI_CLI_AUTH_REQUIRED 说明登录问题，不把它说成项目不存在；连接失败先查地址和服务，不立即新建项目。

## 插件

```bash
roami plugin ls --json
roami plugin info PLUGIN_ID --json
roami plugin audit PLUGIN_ID --json
roami plugin findings --json
roami plugin notifications --json
roami plugin run PLUGIN_ID.COMMAND --key value
```

也支持 `roami PLUGIN_ID COMMAND` 路由。实际插件命令与权限以 info / manifest 为准，不猜命令。读取审计、findings 不等于向外发送消息；可能发送 IM、写远端或启动执行器的插件按实际任务授权使用。

plugin install PATH_OR_TGZ 安装外部插件（默认未启用）；enable/disable、config set/unset、uninstall/restore/purge 是节点管理操作。Agent 的内置工具 / Skill / CLI 不允许启停；不要把另一套插件生命周期当成绕过内置只读限制的方式。plugin track 登记会话退出事件，daemon 为异步收尾进程，不为普通聊天反复启动新守护进程。

## 数据库与服务维护

```bash
roami db status --json
roami db backup /absolute/backup-set
roami db migrate --layout --dry-run
```

迁移、恢复、重启和升级仅在对应任务明确要求时进行；先核对运行任务和一致性备份。`db restore BACKUP_SET` 要空实例，不在活库上覆盖恢复；`migrate --layout --offline` / `--recover` 按实际恢复协议使用。不要用直接 SQL 修改项目、任务、记忆或执行回执绕过服务规则。

## 常见失败如何收敛

| 现象 | 下一步 |
| --- | --- |
| USE_REGISTERED_CLI_CAPABILITY | 搜索受管能力或交给具备完整 CLI 环境的专业 Agent；不套 Shell 绕过 |
| WORKSPACE_REQUIRED | 与项目无关的授权本机操作用 bash scope=host；代码任务复用工作区；网页研究用 resourceOnly |
| TOOL_UNAVAILABLE / 能力空目录 | 核对角色、节点配置和真正已注册的入口，不反复猜工具名 |
| 目标歧义 | 查询完整归属，用选择题列候选，选定后直接执行 |
| queued / running 没有最终回报 | 区分受跟踪任务与旧会话投递，查询现有回执 / 状态，不重复创建 |
| unknown / 场景变化 / 人工接管 | 停止写输入，观察同一资源并对账，不换标签或 key 重放 |
