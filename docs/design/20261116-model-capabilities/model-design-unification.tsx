export default function ModelDesignUnification() {
  return <section className="chapter" id="unification">
    <div className="tt-pagehead"><h2>与“本机网关设计”统一</h2><span className="tag">统一设计边界</span></div>
    <p className="prose">采用一套网关目录、多个选模入口。本机网关负责接入地址、调用 Key、模型目录、聚合管理与调用示例；Roami 设置、首页、任务与 CLI 只选择网关目录里的模型或聚合，不维护第二份目录、Key 或调度池。</p>
    <div className="flow"><div><strong>本机网关</strong><small>配置源、调用 Key、已启用模型与聚合</small></div><div><strong>同一模型视图</strong><small>调用身份、能力证据、费用与可用状态</small></div><div><strong>Roami / 首页</strong><small>分别保存角色默认和当前对话选择</small></div><div><strong>任务 / CLI</strong><small>指定模型或已有聚合，仅覆盖当前执行</small></div></div>
    <div className="table-wrap"><table><thead><tr><th>归属</th><th>统一后的职责</th><th>入口</th></tr></thead><tbody>
      <tr><td>本机网关</td><td>保留“接入与密钥 / 模型目录”，保留卡片、详情检查器、复制调用名称、带入示例和聚合成员 / 权重。</td><td>能力 / 大模型 / 本机网关</td></tr>
      <tr><td>Roami 设置</td><td>只有 Main / Worker 默认模型选择与应用。需要管理时进入同一网关页，返回后继续原选择。</td><td>能力 / 智能体 / Roami</td></tr>
      <tr><td>首页 / 项目</td><td>复用共享选择器；当前对话、单次任务不改角色默认配置。仅上游目录项先启用，不能直接作为执行模型。</td><td>首页输入框 / 项目下任务</td></tr>
      <tr><td>CLI</td><td><code>roami models</code> 是网关能力视图的查询入口；<code>--model</code> 接收同一调用 ID，<code>auto</code> 解析已保存的默认聚合。</td><td>沿用现有 Go CLI 与网关 socket</td></tr>
    </tbody></table></div>
    <details open><summary>需要消除的设计冲突</summary><div className="table-wrap"><table><thead><tr><th>冲突</th><th>统一决定</th></tr></thead><tbody>
      <tr><td>“原生模型”混同“原生能力”</td><td>保留三类目录 Tab，名称明确为“已接入模型 / 聚合模型 / 上游目录”。模型身份另分具体模型、Roami 聚合、上游自动路由、未知；能力交付方式另分 native / adapted / unknown。上游目录是接入状态，不是能力或模型架构。</td></tr>
      <tr><td>两个免费池及不同成员集合</td><td>统一引用网关 <code>free-pool</code>。<code>auto</code> 是选择模式，不新建池。原型 Free pool 有三个明确成员，Coding pool 为权重策略、两个成员、3:1；选模和任务都引用同一成员数组。不得把全部免费模型自动扩成候选池。</td></tr>
      <tr><td>同名模型能力互相矛盾</td><td>网关旧稿给 <code>hy4free</code> 填写的视觉和上下文为合成 fixture，不是生产证据。本稿保留未知；公开模型沿用本次读取快照。真实证据以 source + upstreamModel + protocol + adapter/account 指纹定位，不能仅按名称拼接。</td></tr>
      <tr><td>免费与可调用的承诺不同</td><td>已接入、已启用、健康、能力验证、费用依据、额度分别记录。零价声明不等于全费用免费；手工选择显示未知原因，严格 Auto 仍由 Go 检查能力、价格与额度，失败则等待。</td></tr>
      <tr><td>历史 Key 行内复制</td><td>正式接口历史 Key 仅有哈希，不能从后缀恢复全文。统一原型只在新建 / 轮换后临时显示和复制一次。若未来确需历史全文复制，须另行设计可恢复存储与读取权限；不能把旧静态演示当成现有后端能力。</td></tr>
      <tr><td>两份原型跨 HTML 后数据重置</td><td>当前交付改为一个原型应用，一份页面内目录状态驱动网关卡片、Roami 选择器、调用示例和任务 Auto。启用模型或保存成员后同步可见，不依赖跨 HTML 跳转重载 fixture。</td></tr>
    </tbody></table></div></details>
    <div className="two-col"><div className="stack"><h3>共享技术契约</h3><pre><code>{`ModelView {
  gatewayModelId?: string  // 仅已接入项有对外调用 ID
  sourceId?: string
  upstreamModel?: string
  kind: single | aggregate | unknown
  upstreamRouting: fixed-model | router | unknown
  registration: configured | discovered
  enabled: boolean
  capabilities: Record<CapabilityName, CapabilityFact>
  pricingEvidence: PricingEvidence
  members?: ModelReference[]
  catalogRevision: string
  evidenceRevision: string
}`}</code></pre><p>调用名称、显示名称与上游 ID 分开。API 保留已有 CatalogModel / ModelSource 结构，新增能力视图；兼容公共 <code>/v1/models</code>。共享 <code>ModelCapabilityFacts</code> 和筛选逻辑，网关用卡片密度，选择器用列表密度。</p></div><div className="stack"><h3>落地与集成顺序</h3><ol><li>以网关会话的已确认页面结构、Key 身份和已有实现为基础；最新静态卡片稿与生产实现分别验收。</li><li>Go 统一模型视图与证据、来源范围、目录修订；上游发现项先启用，调用列表不混入仅发现模型。</li><li>将 Roami / 首页 / 任务 / CLI 接到同一视图；固定模型仅覆盖当前作用域，Auto 引用保存的聚合和成员。</li><li>Go 路由先核对任务硬约束，再在该池内应用既有策略。Python 不另建路由或额度准入。</li><li>分别保留网关运行变更和本次设计变更的代码审查。本轮统一设计资料，没有直接合并两个执行中的 worktree 或把网关未审查的运行代码带入文档 PR。</li></ol></div></div>
    <details><summary>对照依据与验收闭环</summary><p>本机网关会话：<code>2026-1112-1808-jl57</code>，检查点 <code>21ca98ec</code>；已读 <code>gateway-design.md</code>、<code>gateway-review.md</code>、<code>gateway-implementation.md</code> 以及对应源码。模型能力会话：<code>2026-1116-1141-fswy</code>，对照检查点 <code>58c750ac</code>。</p><p>原型验收路径：从网关启用一个上游目录项，回 Roami 后可选同一调用 ID；修改聚合成员，任务计划只从更新后的成员中筛选；从模型卡片打开调用示例，示例 ID 与 CLI / 选择器一致；Key 离开明文页后不可恢复全文。</p><p>原型的接入、启用、编辑、Key 均为本地演示；不产生网络模型调用、不改变生产设置。生产网关原有验收不自动覆盖这次能力模型和 CLI 扩展。</p></details>
  </section>
}
