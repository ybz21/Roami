# 轻量列表与滚动分页实现记录

2026-11-02。分支 `fix/initial-load-pagination`，正式服务未部署，无 schema 迁移。
本记录接续前面的诊断和设计阶段；[acceptance.md](acceptance.md) 中“仅文档”描述指早期阶段。

## 已实现的读取边界

| 内容 | 首批 / 续页 | 详情 |
| --- | --- | --- |
| 主对话 | `GET /api/agent/conversations/:cid/messages?limit=50`，`before` 消息 ID，上翻触发 | `GET .../messages/:mid`，长正文点击展开后读取 |
| 任务 | `GET /api/agent/task-list?conversationId=…&limit=20&filter=…`，`before` ID | 继续使用现有任务、资源与产物接口，选中才读取 |
| 通知 | `GET /api/agent/notification-list?limit=20&unreadOnly=…`，事件 ID 游标 | 来源链接定位消息的有限邻近窗口 |
| 未读角标 | `GET /api/agent/notifications/summary`，仅 unread / cursor | 不读取通知正文 |
| 全部已读 | `POST /api/agent/notifications/read`，携带已观察的 eventId 水位 | 保持各会话读取水位单调，不标记之后到达的消息 |
| 记忆 | 现有 catalog 增加 `compact=true`，20 条摘要，继续使用既有 offset 语义 | 既有记录详情接口保留正文与来源 |
| 原生会话 | 复用既有 before / 80 条分页，顶部手势触发 | 本轮不改变原生执行详情数据结构 |

无 limit 的旧消息接口和旧 tasks / notifications 接口保留兼容；Web 改用轻量契约，不自动回退全量下载。
Go 网关显式挂载了新路径；这些路径继续经过认证、节点代理和 Python 所有权校验。

## 模块与一致性

- `conversation/pages.py` 负责谱系遍历、fork 截点、消息游标、锚点窗口与单页预算。
  SQL 先 LIMIT 再解析选中正文；只提供一份 content，常规长文本预览为 2,000 字符。
  内容目标预算为消息 220 KB、整页 256 KB，必要时减少本页条数，游标继续前进。
- `dispatch/task_list.py` 直接投影短标题、真实状态、revision、时间、执行器和必要会话关联；
  不调用逐任务详情组装，不返回 intent / target / budget JSON 或 attempt 报告。
  JSON 标量仍在原表查询；只有列表/详情契约分开，尚未实施物理纵向拆表。
- `replies/notification_pages.py` 统一计数和分页的所有权、删除、遗忘和原生任务可见性过滤。
  通知正文摘要 180 字符，记忆目录摘要 200 字符；通知摘要不会解包所有消息正文。
- SSE 的 `summaries=true` 省去重复 payload_json、完整 activity 预览、路由解释和 tool call 参数，
  默认事件契约兼容。消息 delta 的 contentOffset 仍记录真实字符位置，长预览不因此反复拉取全历史。
- `usePagedAgentData` 和 `useBoundaryLoad` 负责后续页去重、15 秒取消、换筛选/节点隔离、错误重试和真实浏览意图。
  第一次渲染、程序化滚动、布局变化和短列表都不会自动请求下一页；每个触控动作最多一次。
- 主对话 prepend 保留实时消息与当前 snapshotCursor；最近页刷新与更早页合并，不回退实时流。
  “遗忘”事件清空已加载历史窗口并重新验证，避免旧页再次带回已不可见内容。
- 顶部历史容器标记 `data-pagination-edge=start`，手机整页下拉刷新跳过它，避免同一手势双请求。
  新控件沿用设计令牌、按钮和中英文 i18n；未新增图标或产品页结构。

## 同一生产数据快照对比

测量程序用 `mode=ro`、`query_only` 和同一只读事务读取正式 SQLite 与已有 native payload，禁止写回。
比较相同序列化包裹下的 JSON 字节数，不保存口令、Cookie、消息正文或真实 ID。

| 内容 | 旧接口 | 新首批 | 备注 |
| --- | ---: | ---: | --- |
| 主对话 | 4,266,688 B | 57,800 B | 旧 847 条消息；新扫描最多 50 条，隐藏一条自动计划后显示 49 条 |
| 任务 | 221,133 B | 9,990 B | 旧 48 条，新 20 条 |
| 通知 | 305,638 B | 9,014 B | 旧 175 条，新 20 条 |
| 通知角标 | 随完整通知下载 | 36 B | 只含计数和水位 |

[原始脱敏元数据](pagination-comparison.json)。本地函数计时受缓存和并行测试影响，不作为 HTTP、p95 或用户端耗时。
尚未部署，不能把这次比较称为公网首屏耗时下降 98.6%；也没有测量 CPU 或内存收益。

## 独立实例与浏览器

使用 `scripts/dev/isolated-roami.sh /tmp/roami-pagination-case …` 启动生产构建预览，独立配置、数据库、端口和私有 tmux socket。
种子数据含 160 条长短消息、45 条任务、45 条记忆和 30 条通知；不调用模型或生产写接口。

桌面 Chrome：

- 首批 50 条消息，实际 HTTP 响应 51,970 B；摘要 34 B。可见工作区的任务首批 20 条、5,394 B。
- 程序将消息滚动位置设为顶部后仍为 50 条、后续页请求 0；一次实际 PageUp 后 100 条、后续页请求 1。
  之后静置仍为 1；最终构建测得原消息屏幕坐标变化 -0.5 CSS px，阅读位置没有跳回最新。
- 任务点击“加载更多”后 20 → 40 条，恰好一页；选中前没有任务详情请求，点选后才显示完整要求。
- 桌面和手机均静置 30 秒：仍为首批 50 条，后续页 0，消息详情 0，未打开的通知列表请求 0。
- 无文档横向溢出。截图保存于任务临时目录，未提交到 main。

Android：Redmi Note 8，1080 × 2340，DPR 2.75，compact / coarse，页面约 392 CSS px。

- 正式构建经 HTTPS LAN 访问。首批 50 条 / 51,970 B，消息未打开时没有 notification-list 请求。
- 用 ADB 真实下拉历史：50 → 100 条，单次后续页 44,021 B，没有同时触发整页刷新。
- 任务初始 20 条，先程序滚到末尾仍无后续页；ADB 上滑后 40 条，只新增一页，静置不继续排空。
  点按可见任务后才请求该任务详情、资源和产物；已结束详情没有周期轮询。
- 通知打开后首批 20 条，摘要 180 字符；ADB 底部上滑后 40 条，只新增一页。
- 长消息点按“展开全文”前没有消息详情请求，点按后新增一次 21,895 B 的详情请求，显示约 7,200 字符全文。
- 记忆目录初始 20 条 / 18,311 B，ADB 底部上滑后 40 条；点选前没有记录详情请求，点选后新增一次 9,603 B 的详情请求。
- 顶栏按钮命中尺寸 44 CSS px，顶栏与四入口底栏保留，文档 scrollTop 为 0，无横向溢出。
- 当前 Roami 手机 CDP 入口存在实例身份限制，因此触控使用 `roami adb`，只对本任务预览标签用直接 CDP 读取布局和请求断言。

## 自动化验证

验证覆盖权限、fork 继承、游标和同时间戳排序、长消息详情隔离、自动计划隐藏、遗忘过滤、
晚到通知水位、compact memory、SSE 摘要、并发翻页去重、筛选切换、超时重试、每手势一次以及实时消息合并。

- Go：隔离环境 `go test ./...` 通过。首次运行曾遇到既有 Codex completion 时序测试失败，单项和整套重跑均通过；相关执行器代码未修改。
- Python：`uv sync --frozen`、Ruff lint / format 通过；全量 **3028 passed / 48 skipped**。
  最后针对 UTF-8 字节预算、活动锚点、SSE 参数裁剪与原始请求身份投影的修改，再跑 Web 分页、架构及主历史测试，**15 passed**。
- 前端：`npm run typecheck`、`npm run i18n:check`、`npm run hover:check` 通过；完整 Vitest **158 files / 1167 tests passed**；生产构建通过。
  构建仍有仓库现存的大 bundle 提示，未将代码拆包收益计入本轮。
- HTML：内部锚点、ID 唯一性、相对文件链接、内联 JavaScript 语法与 `git diff --check` 通过。
- `scripts/dev/quality/check.sh quick` 通过，包括 Go、Python、前端检查与 secret scan。发布通过关联 PR 管理，正式服务尚未部署。

## 后续边界

普通 JSON 压缩、task_details 拆表、原生会话进一步字段精简、项目扫描解耦和终端 bundle 拆分未包含在本轮。
共享缓存已有 16 MB 上限；活动视图仍随用户主动翻页增长，DOM 窗口化及活动视图内存上限需要后续实现。
记忆沿用 offset，因此并发插入或删除时仍具有 offset 分页的偏移限制；需要更强快照语义时再改 keyset。
最终公网时延、弱网可用时间、整机 CPU / RSS 和 30 次 p50 / p95 需部署后使用相同条件复测。

本任务的预览进程、私有 tmux 测试实例和 Android CDP 转发已清理；测试数据与截图留在 /tmp 供核对。正式服务未重启。

## PR 集成检查

同步主分支 d552b9c6，保留模型相关新增中英文文案并解决插入冲突。完整质量门禁通过（Go、Python、前端检查、生产构建及 secret scan）；完整 Vitest 为 159 个文件、1174 项通过。提交钩子首次遇到既有会话续接时序断言失败，同组在 full 门禁中通过；单独重复 3 次也通过，未修改该执行器逻辑。

补充原基线 20f5005f 的桌面和 Android 截图：使用同一份合成数据，改前 Web 下载 552,364 B 消息和 403,300 B 任务数据，任务列表加载全部 45 条；这与线上数据集的 4.27 MB 测量分开记录。截图不含真实对话。
