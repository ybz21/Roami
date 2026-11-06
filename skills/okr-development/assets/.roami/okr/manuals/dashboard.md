# 看板编辑

## 文件和职责

- `okr.json`：O、KR、指标 metrics、来源和方法；metricId 是稳定引用，名称、单位、账号/稿件与窗口决定数字的含义。
- `dashboard.json`：JSON 的 widgets，或 HTML 的入口、assets、metricIds 和宿主 libraries；只展示数据。
- `dashboard/index.html`：用户实际看到的卡片、表格、图表区域。`data-metric` 是模板约定，并不是自动建指标的接口。
- `dashboard/page.js`：`await okr.ready()` 后，按同一 metricId 调用 `okr.data.read`，再 `subscribe` 自动更新；读 `data.latest.value`、`points`、`asOf`、`quality`。
- `dashboard/style.css`：响应式布局。复用宿主注入的颜色、字号和间距令牌；卡片按内容组织，小屏可滚动，避免横向溢出。

Main 完成定义与最终验收，成员可交付经过核对的页面或数据候选。不要在多处同时改同一份确认配置。

## 新增一个已采集字段

1. 读取当前 `project_okr_context`，或开发终端执行 `roami project okr show <PROJECT_ID> --json`。保存草稿与当前 revision，核对宿主是否支持 HTML、Connector Skill 批次等能力。
2. 找到语义完全匹配的 metricId。缺少用户所需字段就新增指标；不要改名复用另一个指标的历史。播放量不能替代完播率，浏览次数不能替代点击次数。
3. JSON 卡片更新 widgets；HTML 卡片同时更新 metric 定义、`dashboard.html.metricIds` 和 HTML/JS 的同 ID 引用，并列入实际需要的 assets。每个独立数据表/指标组一张卡片，清楚显示单位、统计对象和截至时间。
4. 选择与当前状态对应的确认入口：
   - **文件尚未编辑**：Main 以当前确认配置为底稿，在请求对象中提出完整更改，用支持的 `project_okr_update(operation="save")` 或开发 CLI `roami project okr save <PROJECT_ID> --file <REQUEST_JSON> --json`。保存对象合入 dashboard/team/connectors，不能照搬只读的 observations/projectFiles 等字段。
   - **项目文件已经编辑**：读取最新确认 revision，准备仅含 `revision` 的请求文件，执行 `roami project okr sync <PROJECT_ID> --file <REQUEST_JSON> --json`。`sync` 校验并确认完整文件包；此时 `save` 会因 pending changes 拒绝，不能靠重试 save、删确认指针或覆盖别人草稿来绕过。
   - **新增指标的推荐顺序**：先在未编辑文件的状态下 save 新指标及声明，交宿主生成所需兼容文件；再修改 HTML 卡片并以新 revision sync。旧宿主对未绑定 manual 指标仍会校验 `connectors/<metricId>/connector.json` 和原样的 `store.go` 兼容参考；若已经进入编辑态且缺这些文件，先保留完整草稿，按宿主现有同类导出结构补齐元数据和不改字节的参考文件再 sync。这些是宿主兼容参考，不是让你编写新的 Go 取数插件；实际取数仍放 Connector Skill。
   每次写操作都用刚读取的 revision，保留其他配置与原团队；冲突后重新读取和合并，不盲重试。
5. 按 [取数与入库](data.md) 核验并记录真实观测，再回读确认上下文、数据接口和实际页面。只改 HTML 不会新增历史，只有原始数字文件也不会更新看板。

## 数据接口

页面只通过宿主 SDK 读取被声明的确认数据；不向 iframe 提供凭据，不自己 fetch 数据库、私有 API 或另一个未经确认的 JSON 文件。宿主 ECharts 在 `okr.ready()` 后可用，图表用 `points`；数字卡片用 `latest`，原始日志放交付文件。没有值时显示未知，不能用 `value || 0`。

动态数据与页面定义分开：data 变化保留当前页面，HTML 修改需重新确认完整资源。保留所有无关指标、卡片、KR、历史、来源及团队身份。

## 排查“有数但看板空”

按顺序检查：指标是否确认 → HTML allowlist 是否包含同一 ID → 卡片/JS 是否读取该 ID → 同来源和窗口的观测是否已确认 → 数据接口是否返回该值 → 实际页面是否渲染。平台没有给某个字段时保持未知，不能拿别的值顶上。报告实际显示结果和未解决项，不让用户重复要求“存下数字”。
