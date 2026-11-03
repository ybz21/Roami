# 验收记录

2026-11-03 · [产品设计](README.md) · [技术设计](technical-design.md)

## 已实施

- 桌面、手机统一协作 / 群聊 / 看板三个 Tab，Three.js 真实状态驱动，Main 工位读取真实 turn 状态；草稿、接收人、选择和滚动保持。
- Main 绑定、成员任务、硬依赖、独立验收、原任务续改、幂等、版本失效、暂停/停止/归档、SSE 和私有成员回传。
- 旧页面、SVG/CSS 办公室、广场/手动卡片、旧 HTTP、旧 Go swarm 存储编排、Claude 指挥启动和角色 prompt 已删除；CLI 默认进入新服务。旧说明和安装技能同步更新。
- 历史 schema、备份、会话和文件保留，不做破坏性删除。

## 自动化检查

| 检查 | 结果 |
| --- | --- |
| 首版完整 full 门禁 | 通过；Go 全量、Python uv/ruff/format/pytest、前端 typecheck/i18n/hover/build、secret/staged policy |
| Python 全量 | 3253 passed、48 skipped，843.71s；随后仅删除旧 Go/UI/技能代码，Python 未变化 |
| Python 协作协议 | 14 passed：Main 复用/来源/所有权、DAG/修订冲突、并发解锁、验证门禁、未知不重投、暂停/恢复/归档、群聊幂等、run 绑定、依赖修复、旧停止重放、产物版本 |
| 删除旧实现后的前端全量 | 169 files、1230 tests passed |
| 新 CLI 契约 | 无 commander 参数的 new 调用同一私有 Main 服务；持久键必需；旧 add/adopt/done/activate 拒绝 |
| HTTP 认证 | 新 public 路由复用现有鉴权；私有成员回传不挂到公网代理 |
| 旧 HTTP 真跑 | 新二进制下旧目录/完成/角色入口返回 404，新目录 200，私有成员回传公共地址 404 |
| 能力说明升级 | 精确匹配旧出厂文本时升级；自定义说明不覆盖；新说明不再引导旧命令 |
| 会话 CLI 真跑 | 隔离实例完成 stable ID、发送/捕获、改名保持 ID、旧命令拒绝且不影响会话；经统一入口清理 |
| 最终增量 full / commit quick | 最终增量 full 与提交 quick 均通过；同步 main 后另补 76 项 Python 集成回归。范围从已完整验证的首版 commit 开始，不重复未变化的 Python 全量 |

## 浏览器与 Android

测试服务均经 isolated-roami.sh 启动。UI 测试群手动创建计划后保持暂停，三名成员分别显示 Codex、Claude、Roami 的待派发状态；没有把测试数据写成真实执行成功。改前对照为基线前端与无 Agent 的隔离旧测试群。

- 桌面逻辑宽 1920、页面高 993；document scrollHeight=clientHeight，任务详情打开后文档 scrollTop=0。
- Redmi Note 8（216d6a43），1080×2340、DPR 2.75、CSS 宽 392；document 宽=392，高=clientHeight，document scrollTop=0。
- ADB 实际点按三个 Tab、任务卡片和返回，实际输入、回车换行与返回；草稿切换保持，MobileSubPage 返回保留看板。
- 软键盘高 314 CSS px；composer bottom=439.82，键盘 top=451，发送按钮完整可见。
- 初轮通过 LAN HTTPS 测试。最终对照截图为避免共享 Chrome 的跨端口 cookie 干扰，改用本任务 ADB reverse 的 loopback 源；不据此新增 TLS 行为结论。
- 桌面实际触发 WEBGL_lose_context，显示降级提示，成员 DOM 列表可用，提供重试。

桌面操作使用 roami chrome。Android 的 Roami Chrome 身份探测不可用，DOM 诊断用同一 ADB 转发连接的 CDP，实际触控用 roami adb；没有用 DOM click 替代触控验收。

临时截图在 /tmp/swarm-main-e2e：desktop-before.png、desktop-after.png、desktop-board.png、phone-after.png、phone-board.png、phone-chat-keyboard.png。PR 图片通过 pr-shot.sh 上传孤儿 pr-shots 分支，图片不进入 main。

## Three.js 诊断

同一桌面生产 bundle，显式测试节点在 640×480 场景中绘制 1/8/24 个工位；不改变产品任务状态。

| 工位 | 1s drawElements 调用 | 关闭动画后 400ms | dispose 后 canvas |
| --- | --- | --- | --- |
| 1 | 1760 | 0 | 0 |
| 8 | 9196 | 0 | 0 |
| 24 | 14440 | 0 | 0 |

这是渲染、暂停和卸载诊断，不是 FPS/CPU/内存测试，也不是优化前后对比。真机规模性能、GPU 内存趋势和多次 context restore 仍待补齐，未声称达成 60/30fps。隐藏元素或文档时渲染函数直接返回，不因隐藏页签收到快照继续绘制。

## 未通过与边界

真实 Main 的端到端调用沿用节点保存的模型路线与参数，返回 MODEL_HTTP_401。保存配置没有 API key，对应环境变量未提供；未覆盖真实 Main/Codex/Claude/Roami 多执行器闭环，不使用其他路线绕过验收。截图中的 Main 阻塞提示和红色工位保留此状态。

模型凭据恢复后仍需补真实闭环验收；按用户明确要求推进合入，未将此项标记为通过。相机聚焦、大规模聚合和生产前后性能对比未实施。历史用户数据不自动转换成受管任务。

## 顶层 CLI 补齐

- `roami swarm` 为一级入口，`roami session swarm` 调用同一实现；根帮助、命令帮助、Bash 补全、安装技能与能力说明同步更新。帮助不初始化存储或连接运行时。
- 提供目录、状态、成员、原任务详情、五列看板、群聊、已验收结果，以及成员计划、硬依赖、原任务续改、私有成员回传和生命周期控制；写入保留幂等键与明确修订。
- `chat/status/board --follow` 使用同一 SSE；回放去重、断线退避、游标续接、Ctrl-C 退出，JSON follow 输出 NDJSON。群聊范围是服务最近快照，不承诺无限历史回放。
- 契约和竞态检查覆盖原 task/run/work 身份、验收状态、明确依赖清空、修订重试、SSE 重连和只读帮助；隔离会话 E2E 通过。
- 隔离服务真跑顶层/别名身份一致、成员增加（Roami 映射 native）、依赖设置/清空、暂停幂等重放、实时看板事件、成员/任务/群聊/结果读取、停止与归档。测试群全程暂停，4 个工作项均未派发模型任务，结果汇总保持 0 已验收。
- 本轮仅修改 Go、Shell、技能和文档，Python 检查按增量范围跳过；此前 Python 全量验收继续适用。完整门禁中会话续接测试首次并行运行失败，独立复跑通过，随后采用串行包检查，full 全部通过。
- CLI 帮助和实际输出截图位于 `/tmp/swarm-cli-e2e/cli-help.png`、`cli-views.png`，经 pr-shot.sh 放入 PR 的孤儿图片分支。

## OKR 合并集成

- 合并 `af8d5ece` 的 OKR 工作台，保留嵌入入口并复用受管蜂群组件；嵌入模式不增加返回栏，不恢复旧轮询或旧页面。
- OKR 保存通过同一 CLI 读取受管目录，持久化稳定群 ID；重名、归档和仅存在于旧台账的群拒绝绑定。历史配置保持原值，用户可重新选择有效群。
- 桌面和手机会话分组、全局蜂群计数全部改读共享受管目录，按真实 attempt.sessionId 映射成员；不再读取旧 `/api/swarms*` 或为每群额外请求详情。
- Main 群聊没有 taskId 时保持 Main 归属，不匹配尚未派发的成员。后端绑定与前端嵌入/消息归属的回归测试通过。
- 隔离实例通过真实 CLI 创建项目、暂停受管群、添加未派发成员，并以相同群 ID 保存 OKR。测试未启动成员模型任务，Main 仍显示实际模型认证失败。
- 桌面 1280/1920/2560/3440 CSS px 均无文档溢出，嵌入面板填满剩余工作区。Android ADB 实际切页签、输入草稿、开任务详情、返回和滑动；草稿保持、URL 不变、详情返回后留在看板，document.scrollTop=0、scrollWidth=392。
- 新截图 `okr-desktop.png`、`okr-phone-board.png` 通过 pr-shot.sh 上传；截图保留暂停和模型阻塞状态。
- 合并后的前端全量：177 files、1269 tests passed；typecheck、i18n 与 hover 检查通过。
