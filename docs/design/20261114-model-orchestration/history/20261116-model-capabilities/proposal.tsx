import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useLayout } from '../../../../../frontend/src/layout'
import { ChevronLeft, CloseIcon } from '../../../../../frontend/src/icons'
import evidence from './model-evidence.json'
import ModelDesignUnification from './model-design-unification'

type Model = {
  id: string; route: string; name: string; kind: 'single' | 'router' | 'unknown';
  input: string[] | null; tools: boolean | null; reasoning: boolean | null;
  schema: boolean | null; json: boolean | null; context: number | null;
  output: number | null; free: boolean | null;
}
const routes = ['or-lightning-free', 'or-super-vl-free', 'or-free-router', 'or-particle-free', 'or-flint-free', 'or-inkling-free']
const screenshotIDs = ['nvidia/nemotron-3.5-lightning:free', 'nvidia/nemotron-3.5-super-vl:free', 'openrouter/free', 'particle-ai/particle-1:free', 'recursive/flint-v1.0:free', 'thinkingmachines/inkling-2-small:free']
const models: Model[] = screenshotIDs.map((id, i) => {
  const row = evidence.models.find(item => item.id === id)!
  return { id, route: routes[i], name: row.name, kind: id === 'openrouter/free' ? 'router' : 'single',
    input: row.architecture.input_modalities, tools: row.supported_parameters.includes('tools'),
    reasoning: row.supported_parameters.includes('reasoning'), schema: row.supported_parameters.includes('structured_outputs'),
    json: row.supported_parameters.includes('response_format'), context: row.context_length,
    output: row.top_provider.max_completion_tokens,
    free: row.pricing.prompt === '0' && row.pricing.completion === '0' }
})
models.push(...['hy4free', 'workbuddy-hy4'].map(id => ({ id, route: id, name: id, kind: 'unknown' as const,
  input: null, tools: null, reasoning: null, schema: null, json: null, context: null, output: null, free: null })))
const kindName = { single: '具体模型', router: '上游自动路由', unknown: '待核对' }
const bool = (value: boolean | null) => value === null ? '未知' : value ? '声明支持' : '未声明支持'
const modality: Record<string,string> = { text: '文本', image: '图片', audio: '音频', video: '视频', file: '文件' }
declare const __DOCUMENT_KIND__: 'technical' | 'prototype'
const isPrototype = __DOCUMENT_KIND__ === 'prototype'
function Code({ children }: { children: string }) { return <pre><code>{children}</code></pre> }
function Tag({ children, tone = '' }: { children: React.ReactNode; tone?: string }) { return <span className={'tag ' + tone}>{children}</span> }
function RoutingRules({ expanded = false }: { expanded?: boolean }) { return <details open={expanded}><summary>调度规则与失败边界</summary><ul><li>图片等输入模态从实际请求推导；工具、JSON Schema、输出预算和上下文形成硬约束。显式要求只能增加约束，不能关掉真实附件要求。推理参数仅向支持路径发送，不静默删除用户要求。</li><li>实际能力是“模型声明、协议转换、插件适配、账号权限、执行器支持”的交集。选中图片模型后仍必须验证附件编码与传输；文件转文字或 OCR 标为适配能力，不能冒充原生图片/文件输入。</li><li>聚合对外区分“所有可调度成员均支持”与“按请求可选到支持者”；不使用成员能力并集作无条件承诺。上下文按候选可用窗口检查输入、工具定义和输出预留，未知上限不参与严格调度。</li><li>Auto 默认不纳入不透明的上游路由。显式纳入时，须验证该路由能够强制满足本次能力、上下文与费用约束；仅有 Models API 声明仍不足。响应记录上游返回的真实模型，缺失则为 unknown。</li><li>模型选择按任务/轮次冻结，跨轮只在可恢复边界变更。流已输出、工具已执行或结果未知时，先核对停止和副作用证据；不盲目从头重试。确定未执行的 429 等错误才按现有退避与候选策略处理。</li><li>“Auto”是选择已配置池的模式；“smart”是池内既有路由策略。按任务复杂度分类、低难任务交给轻量模型属于后续阶段，不能在首期宣称已具备。</li></ul></details> }
function App() {
  const { phone } = useLayout()
  const [theme, setTheme] = useState('dark')
  const [query, setQuery] = useState(''), [kind, setKind] = useState('all')
  const [required, setRequired] = useState<string[]>([]), [minContext, setMinContext] = useState('0')
  const [selected, setSelected] = useState<Model | null>(null)
  const [role, setRole] = useState('main'), [roleModels, setRoleModels] = useState<Record<string,string>>({ main: 'workbuddy-hy4', worker: 'free-pool' })
  const [pickerQuery, setPickerQuery] = useState(''), [pickerCaps, setPickerCaps] = useState<string[]>([]), [pickerKind, setPickerKind] = useState('all')
  const [notice, setNotice] = useState('')
  const [scenario, setScenario] = useState('image'), [freeOnly, setFreeOnly] = useState(true), [requireVerified, setRequireVerified] = useState(false)
  const [includeRouter, setIncludeRouter] = useState(false), [offline, setOffline] = useState(false)
  const [strategy, setStrategy] = useState('order'), [planned, setPlanned] = useState(false)
  const supports = (m: Model, cap: string) => cap === 'free' ? m.free === true : cap === 'tools' ? m.tools === true : cap === 'reasoning' ? m.reasoning === true : cap === 'schema' ? m.schema === true : m.input?.includes(cap) === true
  const visible = models.filter(m => (m.id + m.name).toLowerCase().includes(query.toLowerCase()) && (kind === 'all' || m.kind === kind) && required.every(cap => supports(m, cap)) && (!Number(minContext) || (m.context || 0) >= Number(minContext)))
  const toggle = (cap: string) => setRequired(value => value.includes(cap) ? value.filter(v => v !== cap) : [...value, cap])
  const picker = models.filter(m => (m.id + m.name).toLowerCase().includes(pickerQuery.toLowerCase()) && pickerCaps.every(cap => supports(m, cap)) && (pickerKind === 'all' || m.kind === pickerKind))
  const poolVisible = (pickerKind === 'all' || pickerKind === 'aggregate') && 'free-pool 免费任务池'.includes(pickerQuery.toLowerCase()) && models.some(m => m.kind === 'single' && pickerCaps.every(cap => supports(m,cap)))
  const constraints = scenario === 'image' ? ['image','tools'] : scenario === 'schema' ? ['tools','schema'] : scenario === 'audio' ? ['audio','tools'] : ['tools']
  const exclusion = (m: Model) => {
    if (offline) return '演示渠道额度已耗尽'
    if (m.kind === 'unknown') return '类型与能力未知'
    if (m.kind === 'router' && !includeRouter) return '上游自动路由默认不入池'
    if (m.kind === 'router') return '上游路由约束尚未验证'
    if (freeOnly && m.free !== true) return '免费依据不足'
    const missing = constraints.filter(cap => !supports(m,cap))
    if (missing.length) return '缺少声明：' + missing.map(cap => ({tools:'工具调用',schema:'JSON Schema',image:'图片输入',audio:'音频输入'}[cap])).join('、')
    if (requireVerified) return '尚无端到端验证证据'
    return ''
  }
  const candidates = models.filter(m => !exclusion(m))
  const choose = (id: string) => { setRoleModels(v => ({ ...v, [role]: id })); setNotice('已更新演示选择；未写入节点配置。') }
  return <div className="app">
    <header className="topbar"><span className="wordmark">Roami</span><span className="meta">模型能力与 Auto 调度</span><Tag>{isPrototype ? '原型设计' : '技术设计'}</Tag><button type="button" onClick={() => { const next = theme === 'dark' ? 'light' : 'dark'; setTheme(next); document.documentElement.dataset.theme = next }}>{theme === 'dark' ? '浅色' : '深色'}</button></header>
    <nav className="document-nav" aria-label="设计文档">
      <a href="technical-design.html" aria-current={!isPrototype ? 'page' : undefined}>技术设计</a>
      <a href="prototype.html" aria-current={isPrototype ? 'page' : undefined}>原型设计</a>
    </nav>
    <div className="frame">
    <main>
      {isPrototype ? <>
      <section className="chapter" id="catalog">
        <div className="tt-pagehead"><div><h2>能力目录</h2><p className="meta">附件逐项核对 · 公开声明快照，未验证本节点调用链路</p></div><Tag>可筛选演示</Tag></div>
        <div className="filters"><label className="field search">模型名称<input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索名称或上游 ID" /></label><label className="field">模型类型<select value={kind} onChange={e => setKind(e.target.value)}><option value="all">全部类型</option><option value="single">具体模型</option><option value="router">上游自动路由</option><option value="unknown">待核对</option></select></label><label className="field">最小上下文<select value={minContext} onChange={e => setMinContext(e.target.value)}><option value="0">不限</option><option value="262144">262,144 tokens</option><option value="1000000">1,000,000 tokens</option></select></label></div>
        <div className="row">{[['image','图片输入'],['audio','音频输入'],['video','视频输入'],['file','文件输入'],['tools','工具调用'],['reasoning','推理'],['schema','JSON Schema'],['free','目录零价']].map(([key,label]) => <label className="check" key={key}><input type="checkbox" checked={required.includes(key)} onChange={() => toggle(key)} />{label}</label>)}{required.length > 0 && <button type="button" className="quiet" onClick={() => setRequired([])}>清除能力条件</button>}</div>
        <p className="note">区分具体模型、Roami 聚合与上游自动路由；能力来自公开声明，尚未验证本节点链路。</p>
        <div className="catalog-work"><div className="catalog-main"><div className="table-wrap"><table className="catalog-table"><thead><tr><th>模型 / 来源</th><th>类型</th><th>输入</th><th>工具 / 推理</th><th>结构化输出</th><th>上下文</th></tr></thead><tbody>{visible.map(m => <tr key={m.id} className={selected?.id === m.id ? 'selected' : ''}><td><button type="button" className="name" onClick={() => setSelected(m)}>{m.name}</button><small><code>{m.id}</code></small><small>{m.kind === 'unknown' ? '本地名称，映射待核对' : 'OpenRouter · 目录零价'}</small></td><td data-label="类型">{kindName[m.kind]}</td><td data-label="输入">{m.input?.map(v => modality[v]).join('、') || '未知'}</td><td data-label="工具 / 推理">{m.tools === null ? '未知' : '均声明支持'}</td><td data-label="结构化">{m.schema ? 'JSON Schema' : m.json ? 'response_format' : m.schema === null ? '未知' : '未声明'}</td><td data-label="上下文">{m.context?.toLocaleString('zh-CN') || '未知'}</td></tr>)}</tbody></table></div>{!visible.length && <p className="empty">没有符合条件的模型。</p>}</div>
        {selected && <aside className="inspector" aria-label="模型详情"><div className="tt-pagehead">{phone && <button type="button" className="quiet iconbutton" aria-label="返回能力目录" onClick={() => setSelected(null)}><ChevronLeft /></button>}<h3>模型详情</h3>{!phone && <button type="button" className="quiet iconbutton" aria-label="关闭模型详情" onClick={() => setSelected(null)}><CloseIcon /></button>}</div><dl><dt>上游模型 ID</dt><dd><code>{selected.id}</code></dd><dt>身份类型</dt><dd>{kindName[selected.kind]}</dd><dt>Roami 目录 ID（示例）</dt><dd><code>{selected.route}</code></dd><dt>图片输入</dt><dd>{selected.input === null ? '未知' : selected.input.includes('image') ? '上游声明支持 · 路径未验证' : '目录未声明支持'}</dd><dt>工具调用 / 推理</dt><dd>{bool(selected.tools)} / {bool(selected.reasoning)}</dd><dt>JSON Schema / response_format</dt><dd>{bool(selected.schema)} / {bool(selected.json)}</dd><dt>最大输出</dt><dd>{selected.output?.toLocaleString('zh-CN') || '未知'} tokens</dd><dt>链路与额度</dt><dd>未验证 · 本地启用状态、认证和剩余额度待读取</dd><dt>证据</dt><dd>{selected.kind === 'unknown' ? '仅附件；不能按 free 后缀断言免费，也不能按历史设计示例推断能力。' : <a href="https://openrouter.ai/api/v1/models" target="_blank" rel="noreferrer">OpenRouter Models API</a>}</dd></dl>{selected.kind === 'router' && <p className="note">上游会继续选具体模型。实际模型需从响应或回执读取，无法读取时记为未知；不得将目录能力当作每个落点的保证。</p>}<p className="meta">点击行打开详情；桌面关闭后目录收回全部宽度，手机使用全屏返回页。</p></aside>}
        </div>
        <details><summary>附件对应的结论与原图</summary><p>5 个具体模型：Lightning、Super VL、Particle-1、Flint、Inkling 2 Small。1 个上游路由：<code>openrouter/free</code>。2 个本地名称：<code>hy4free</code>、<code>workbuddy-hy4</code>，须检查实际候选图，才能判断是否为 Roami 聚合。</p><p>具体模型中 Super VL、Particle-1、Inkling 2 Small 声明支持图片；Lightning 与 Flint 未声明图片。<code>openrouter/free</code> 也声明可接收图片，其落点动态变化。所有结论限于本次公开快照。</p><img className="reference" src="assets/reference-input.png" alt="用户提供的现有主智能体模型下拉，包含八个待区分能力的模型名称" /></details>
      </section>
      <section className="chapter" id="roami">
        <div className="tt-pagehead"><h2>Roami 中也能按能力选择</h2><Tag>交互演示</Tag></div>
        <div className="two-col"><div className="demo stack"><div className="tabs" role="tablist" aria-label="选择角色">{[['main','主智能体'],['worker','执行智能体']].map(([id,label]) => <button type="button" role="tab" aria-selected={role === id} key={id} onClick={() => {setRole(id); setNotice('')}}>{label}</button>)}</div><p>当前演示选择：<code>{roleModels[role]}</code></p><label className="field">查找模型<input placeholder="名称或 ID" value={pickerQuery} onChange={e => setPickerQuery(e.target.value)} /></label><div className="row"><label className="field">类型<select value={pickerKind} onChange={e => setPickerKind(e.target.value)}><option value="all">全部类型</option><option value="single">具体模型（原生身份）</option><option value="aggregate">Roami 聚合</option><option value="router">上游自动路由</option><option value="unknown">待核对</option></select></label></div><div className="row">{[['image','图片输入'],['audio','音频输入'],['video','视频输入'],['file','文件输入'],['tools','工具调用'],['reasoning','推理'],['schema','JSON Schema'],['free','目录零价']].map(([cap,label]) => <label className="check" key={cap}><input type="checkbox" checked={pickerCaps.includes(cap)} onChange={() => setPickerCaps(v => v.includes(cap) ? v.filter(c => c !== cap) : [...v,cap])} />{label}</label>)}</div><div>{poolVisible && <div className="choice-row"><div><strong>Auto · 免费任务池</strong><code>Roami 聚合示例 · 按请求筛选成员 · 未验证</code></div><button type="button" aria-pressed={roleModels[role] === 'free-pool'} onClick={() => choose('free-pool')}>选择</button></div>}{picker.map(m => <div className="choice-row" key={m.id}><div><strong>{m.name}</strong><code>{kindName[m.kind]} · {m.input?.includes('image') ? '声明图片输入' : m.input === null ? '能力未知' : '文本输入'} · 未验证</code></div><button type="button" aria-label={'选择 '+m.name} aria-pressed={roleModels[role] === m.route} onClick={() => choose(m.route)}>选择</button></div>)}{!picker.length && !poolVisible && <p className="empty">没有符合条件的模型。</p>}</div><p className="notice" role="status">{notice}</p></div>
        <div className="stack"><h3>入口与选择范围</h3><ul><li>设置 / 能力 / Roami：Main、Worker 共用能力选择器，分别保存默认模型。</li><li>首页模型选择：复用相同搜索、类型与能力筛选。手机沿用全屏模型页，不把长列表塞进对话框。</li><li>新对话、启动与新建任务：支持“沿用默认 / 指定模型 / Auto 池”，同时显示作用范围。</li><li>Roami 聚合行展示“聚合”与成员数量；具体模型行展示源与关键能力；上游路由明确显示“上游自动”。</li></ul><h3>状态与保存</h3><p>当前选择即使被筛掉也留在顶部，不自动选第一项。未接入的目录模型显示“去接入”，不可直接执行；禁用、离线和能力未知显示原因。原型里的选择仅修改页面内演示状态。</p><p>配置页保存沿用 revision 检查和现有角色绑定接口；失败保留草稿。正在运行的对话不热切换模型，下一轮安全边界应用；显式任务覆盖不修改默认设置。</p><h3>能力声明编辑</h3><p>源内“模型详情 / 能力”允许逐项选择“未知、支持、不支持”，记录依据与作用路径；“原生 / 适配 / 未知”单独记录。限制能力可以立即生效，提高能力必须验证后才能用于严格 Auto。聚合能力由成员与约束推导，不能手工全选为支持。</p><p className="note">正式 UI 新文案接入项目中英文 i18n；本设计文档按仓库开发者文档例外使用中文。桌面沿用现有导航与组件；手机保留宿主顶栏、底栏和单个全屏返回层。</p></div></div>
      </section>
      <section className="chapter" id="auto">
        <div className="tt-pagehead"><h2>Auto 先筛能力，再选路径</h2><Tag>交互式计划预览</Tag></div>
        <div className="flow"><div><strong>读取要求</strong><small>图片、工具、输出格式、上下文</small></div><div><strong>排除不匹配</strong><small>能力未知、禁用、过期与无额度</small></div><div><strong>应用策略</strong><small>复用顺序、便宜、智能等既有策略</small></div><div><strong>记录落点</strong><small>具体源、模型、路由版本与原因</small></div></div>
        <div className="two-col"><div className="demo stack"><label className="field">任务要求<select value={scenario} onChange={e => {setScenario(e.target.value); setPlanned(false)}}><option value="image">看截图并调用工具</option><option value="text">整理文本并调用工具</option><option value="schema">提取 JSON Schema 结果</option><option value="audio">理解音频并调用工具</option></select></label><div className="row"><label className="check"><input type="checkbox" checked={freeOnly} onChange={e => {setFreeOnly(e.target.checked); setPlanned(false)}} />仅目录零价</label><label className="check"><input type="checkbox" checked={requireVerified} onChange={e => {setRequireVerified(e.target.checked); setPlanned(false)}} />必须已验证</label><label className="check"><input type="checkbox" checked={includeRouter} onChange={e => {setIncludeRouter(e.target.checked); setPlanned(false)}} />纳入上游路由</label><label className="check"><input type="checkbox" checked={offline} onChange={e => {setOffline(e.target.checked); setPlanned(false)}} />模拟额度耗尽</label></div><label className="field">路由策略<select value={strategy} onChange={e => {setStrategy(e.target.value); setPlanned(false)}}><option value="order">按优先顺序</option><option value="cheap">便宜优先</option><option value="smart">现有智能策略</option></select></label><button type="button" className="primary" onClick={() => setPlanned(true)}>预览计划</button><p className="meta">默认按公开声明解释候选；开启“必须已验证”会得到空池，因为本次没有调用模型验证。正式 Auto 默认开启验证要求。</p>{planned && <div className="result" role="status"><strong>{candidates.length ? `${candidates.length} 个候选满足声明条件` : '没有满足条件的候选'}</strong><p>{candidates.length ? `计划首选：${candidates[0].id}` : '保留任务，等待可用额度或补齐验证；不转付费路径。'}</p><p className="meta">{strategy === 'order' ? '按列表优先级选第一个。' : strategy === 'cheap' ? '本快照候选文本零价相同，以优先级打破平局；正式运行须核对全费用。' : '本原型无真实健康、速度和额度数据，以优先级占位；不伪造智能评分。'} 这只是计划，没有发起模型调用。</p></div>}</div><div className="stack"><h3>逐项解释候选</h3><div>{models.map(m => <div className="choice-row" key={m.id}><div><code>{m.id}</code><span className={exclusion(m) ? 'meta' : 'ok'}>{exclusion(m) || '符合声明条件，待正式路径验证'}</span></div></div>)}</div></div></div>
        <RoutingRules />
      </section>
      </> : <>
      <section className="chapter" id="overview">
        <div className="tt-pagehead"><h1>模型能力与 Auto 调度：技术设计</h1><Tag tone="accent">技术设计</Tag></div>
        <div className="intro"><div><p>同一份模型能力目录，供设置、首页、启动命令和任务调度使用。选择时看清具体模型、Roami 聚合或上游自动路由，按图片、工具调用等条件筛选；也可以选择 Auto，让网关在满足条件的候选中调度。</p><p>技术设计包含能力数据、CLI 契约、调度与长时任务方案；演示使用附件中的 8 个名称和公开目录快照。阶段一已实现模型目录、CLI 与原生会话选模；其余能力证明与长时调度仍为设计。实际范围见同目录 implementation.md。</p></div><aside className="summary"><strong>三个关键决定</strong><p>类型、能力、计费分开建模。</p><p>未知能力不进入严格调度。</p><p>指定模型只影响当前启动或任务。</p></aside></div>
        <details><summary>用户故事与现有基础</summary><div className="two-col"><ul><li>作为使用者，我能筛出支持图片的免费模型，并看清能力来源。</li><li>作为 CLI 使用者，我能列出模型能力，为新对话或新会话指定模型。</li><li>作为任务编排者，我能为单次任务选择具体模型或 Auto 池，不修改 Main/Worker 默认值。</li><li>作为长时任务使用者，我能在免费额度恢复后继续，不丢检查点，不自动付费。</li></ul><div className="stack"><p>现有 <code>CatalogModel.aggregate</code>、候选图、九种路由策略、<code>freeOnly</code>、<code>requireTools</code> 与 <code>minContext</code> 可复用。源目录已读取输入输出模态、工具、推理和价格；Roami 模型下拉目前主要展示名称。</p><p><code>roami model list</code> 已读取 Go 网关能力目录；新对话与原生 Worker 任务已支持单次选模。外部执行器沿用已有 spec 的 <code>model</code> 字段。</p></div></div></details>
      </section>
      <ModelDesignUnification />
      <section className="chapter" id="architecture">
        <div className="tt-pagehead"><h2>一份能力数据，多个选择入口</h2><Tag>Technical Design</Tag></div>
        <div className="two-col"><div className="stack"><h3>能力记录与证据</h3><Code>{`type CapabilityState = "supported" | "unsupported" | "unknown"
type CapabilityFact = {
  state: CapabilityState
  delivery: "native" | "adapted" | "unknown"
  basis: "advertised" | "manual" | "verified"
  observedAt: string
  expiresAt?: string
  sourceRevision: string
  pathFingerprint: string
  evidenceRef?: string
}
type ModelIdentity = {
  kind: "single" | "aggregate" | "unknown"
  upstreamRouting: "fixed-model" | "router" | "unknown"
  sourceId?: string
  upstreamModel?: string
}`}</Code><p><code>kind</code> 描述 Roami 路由图：<code>aggregate=true</code> 明确标聚合；固定主模型及备用路径检查身份，无法证明固定模型时为 unknown。上游路由用独立字段表示，UI 显示“上游自动”。源类型另列 direct / aggregator / plugin / unknown，不能按模型 ID 前缀猜来源。</p><p>声明与验证分层保存，不互相覆盖。人工信息带操作者、依据和时间；发现失败保留旧快照并标过期。新的高能力声明只有匹配路径验证后才进入严格池；明确的限制立即收窄。</p></div><div className="stack"><h3>标准字段</h3><div className="table-wrap"><table><thead><tr><th>领域</th><th>字段与语义</th></tr></thead><tbody><tr><td>输入 / 输出</td><td>text、image、audio、video、file；输入和输出分别记录，不以图片输入推断图片生成。</td></tr><tr><td>工具</td><td>tools、tool_choice、parallel_tools 分开；支持工具调用不等于任意执行器都兼容。</td></tr><tr><td>结构化</td><td>response_format / json_object 与严格 json_schema 分开，不能用 JSON 文本代替 Schema 保证。</td></tr><tr><td>生成与推理</td><td>streaming、reasoning、可用 effort 档位、temperature 等参数白名单；缺失为未知。</td></tr><tr><td>容量</td><td>contextWindow、maxOutputTokens；精确 tokens 与证据时间，未知不填 0。</td></tr><tr><td>费用与可用性</td><td>free / quota / metered / unknown；输入、输出、图片及工具费用单列。健康、禁用、限流与余额独立。</td></tr><tr><td>证据范围</td><td>source + model + protocol + adapter revision + account 权限指纹；凭据变更失效，不保存密钥。</td></tr></tbody></table></div><p>上游清单常聚合多个 provider 的能力；当前账号、具体端点与协议仍需收窄验证。目录刷新默认按源显式执行，合并并发，按修订缓存；页面隐藏停轮询，不为每个模型建立定时器。</p></div></div>
        <details><summary>接口与模块架构</summary><div className="table-wrap"><table><thead><tr><th>层</th><th>现有位置</th><th>建议增量</th></tr></thead><tbody><tr><td>上游声明归一化</td><td><code>internal/agentproviders/source-model-detail.go</code><br/><code>internal/modelgateway/source_models.go</code></td><td>保留 supported_parameters，扩展结构化、流式与参数支持；插件假值缺失不能默认当 false。加入证据时间与修订。</td></tr><tr><td>Go 能力服务</td><td><code>internal/modelgateway/catalog*.go</code><br/><code>routing_choice.go</code></td><td>新增按领域命名的 <code>model_capabilities.go</code> 与 <code>capability_evidence.go</code>；统一 effective capabilities、路径指纹、候选排除与免费判定，复用现有验证记录机制。</td></tr><tr><td>查询 API</td><td>现有 <code>/v1/model-gateway/catalog</code> 及公共模型协议</td><td>拟增 <code>GET /v1/model-gateway/models</code> 返回能力视图，Web 使用现有代理；保留 <code>/v1/models</code> 兼容结构，扩展属性放命名空间中，不强迫客户端理解内部证据。</td></tr><tr><td>CLI</td><td><code>cmd/roami/agent-gateway.go</code> 与现有命令注册</td><td>已实现 <code>roami model list</code>；原生会话将模型写入现有任务记录，实际调用时由网关验证。fork 仍保持既有 shell 派生语义。</td></tr><tr><td>对话 / 任务运行时</td><td><code>agent-runtime/src/roami_agent/dispatch/tasks.py</code><br/><code>internal/agentexecution/execution.go</code></td><td>复用 native Worker 任务 intent 的 model 字段，执行时传入现有 Provider；Python 不实现第二套路由或配额准入。隔离外部执行器配置，不能为单次覆盖改全局账号配置。</td></tr><tr><td>前端</td><td><code>RoamiAgentModels.tsx</code>、<code>useAgentModels.ts</code>、<code>ModelSourceEditor.tsx</code></td><td>新增 <code>ModelCapabilityPicker.tsx</code> 与 <code>ModelCapabilityFacts.tsx</code> 供首页/设置/任务复用；导航草稿使用 view-state 的 node/page/resource 作用域，不增全局 Map。</td></tr></tbody></table></div><p className="note">以 revision 做写入并发控制，以路径指纹控制能力证据失效；运行记录存请求模型 ID、解析后的目录 ID、源、上游模型、实际模型、任务修订、费用依据和选择原因。公开错误只提供下一步，技术细节按需展开。</p></details>
      </section>
      <section className="chapter" id="cli">
        <div className="tt-pagehead"><h2>CLI 与启动配置</h2><Tag tone="ok">阶段一命令已实现</Tag></div>
        <div className="two-col"><div className="stack"><h3>列出全部模型及能力</h3><Code>{`# 已接入模型与缓存能力
roami model list
roami model list --json
roami model list --capability image

# 显式刷新上游目录；未接入项不能直接调用
roami model list --refresh --all --json

# 已确认免费的单模型与仅免费聚合池
roami model list --free

# 缺失能力保留 unknown；聚合能力不取成员并集
# advertised-zero 不是免费路由保证`}</Code><p>“全部”是节点已接入目录与缓存，不代表自动读取互联网所有模型。仅上游目录项没有可调用的 Roami ID；返回 <code>sourceId + upstreamModel</code>，接入后才分配目录 ID。当前列表展示配置与启用状态；健康、额度与严格调度条件继续按后续设计完善。</p><p><code>model list</code> 默认只读配置与缓存；刷新显式发现上游模型，不触发推理。JSON 返回能力声明、未知状态、计价分类与目录修订，不返回密钥。</p></div><div className="stack"><h3>为当前启动指定模型</h3><Code>{`# 创建持久的 Roami 原生任务会话
roami session new 整理资料 --kind roami --model free-pool --free-only \\
  --task "整理本机资料" --dir /absolute/path --key research-task --json

# 原生会话创建同时兼容 -model
roami session new 调研 --kind roami -model free-pool --task "整理资料"

# Auto 使用已绑定网关的角色模型，不扫描上游目录
roami session new 调研 --kind roami --model auto --task "整理资料"

# 外部执行器沿用已有 JSON spec.model
roami agent execution launch --file task.json`}</Code><p><code>auto</code> 保留为 Auto 选择标识，沿用当前角色保存的模型或池。<code>free-pool</code> 是用户保存的聚合目录 ID，名称本身不证明免费。</p><p>首页选择器从网关动态显示模型名称和原生 / 聚合类型；打开列表时刷新节点当前选择。Agent 沿用原有 <code>delegate</code> 工具，模型或聚合池 ID 与免费条件写入已有任务记录：</p><Code>{`{"goal":"整理资料","executor":"native","model":"free-pool","freeOnly":true}`}</Code><p>原生任务显式选择优先于角色默认值；外部执行器沿用 JSON spec 的模型字段。显式 <code>--model</code> 只覆盖目标执行，不写全局配置；固定模型不得静默换成另一模型。</p><p>目录 ID 与上游 ID 分开。含斜杠的上游名称不直接作为目录 ID；先在模型源中接入，再使用网关调用名称选择，禁止仅凭同名猜来源。会话续接沿用已绑定执行器，模型变更走受管 steer 与当前任务 revision。</p></div></div>
        <details><summary>配置、JSON 回执与错误语义</summary><div className="two-col"><div className="stack"><Code>{`// 持久化到现有节点 / 角色配置的建议增量（JSON 示意）
{
  "main": {
    "modelSelection": { "mode": "fixed", "modelId": "or-super-vl-free" }
  },
  "worker": {
    "modelSelection": { "mode": "auto", "poolId": "free-pool" }
  }
}`}</Code><p>这不是新的顶层配置文件。沿用现有模型设置与节点路径；旧 <code>model</code> 按 fixed 迁移，不把既有 <code>strategy=smart</code> 自动改成“按任务复杂度分类”。</p><Code>{`// models --json 单项（建议）
{
  "id": "or-super-vl-free",
  "kind": "single",
  "upstreamRouting": "fixed-model",
  "capabilities": {
    "image_input": {
      "state": "supported", "basis": "advertised",
      "delivery": "unknown", "verified": false
    }
  },
  "availability": "unverified",
  "catalogRevision": "...", "evidenceRevision": "..."
}`}</Code></div><div><ul><li><code>MODEL_NOT_FOUND</code>：未接入或来源不唯一，列出接入入口。</li><li><code>MODEL_CAPABILITY_MISMATCH</code>：明确缺少的能力，不提交调用。</li><li><code>MODEL_CAPABILITY_UNKNOWN</code>：没有可信证据，不把未知当不支持。</li><li><code>MODEL_POOL_EMPTY</code>：列出被排除原因，保留任务并等待或由用户调整池。</li><li><code>MODEL_SELECTION_UNSUPPORTED</code>：执行器不支持覆盖，在创建会话与工作区之前拒绝。</li><li><code>MODEL_CATALOG_CHANGED</code>：重新读取目录，不自动重放已产生外部效果的操作。</li><li>拟定退出码：参数错误 2、目录/能力约束错误 3、暂不可用 4、其余失败 1；成功 0。JSON 错误用稳定机器码，终端输出可使用中文。</li></ul><p className="note">不增加独立工具或第二套 CLI。网关仍由 Go 管理，CLI 通过已有私有 socket 请求同一目录服务；Web 与 CLI 返回相同能力解释。</p></div></div></details>
      </section>
      <section className="chapter" id="routing"><div className="tt-pagehead"><h2>Auto 调度与失败边界</h2></div><RoutingRules expanded /></section>
      <section className="chapter" id="longrun">
        <div className="tt-pagehead"><h2>用免费模型承接可恢复的长时任务</h2><Tag>未来规划</Tag></div>
        <div className="three-col"><div className="stack"><h3>先承接低成本、可验证的步骤</h3><p>从分类、资料整理、去重、格式转换和摘要草稿开始；用结构校验、规则检查、测试或抽样审阅判断结果。复杂步骤留给显式指定的高能力模型。</p><p>免费池来自用户已接入、已启用的模型。新发现的免费目录项先展示与验证，不自动加入运行池。</p></div><div className="stack"><h3>额度不足就等待</h3><p>Go 网关统一判定费用、剩余额度、共享账号限制与冷却；Python 只记录使用量并执行网关决定。读到 Retry-After 或重置时间后进入持久等待，带抖动退避，不循环撞接口。</p><p>价格未知、免费声明过期或额外图片/工具费用无法确认时，不进入“严格免费”路径。套餐余额单列，只有显式允许时才使用。</p></div><div className="stack"><h3>任务持续，调用按需发生</h3><p>每个工作单元保存输入引用、结果、模型、任务 revision、检查点和幂等键。网关返回下一次允许时间后释放执行资源，定时或事件唤醒；重启后恢复等待，不依赖一个常驻热循环。</p><p>免费调用仍受提供方容量限制。系统提供等待、恢复和手动停止；不承诺无限额度或连续可用。付费升级必须显式开启并遵守现有网关准入。</p></div></div>
        <p className="note">任务状态建议：排队、执行中、等待额度、待核对、已完成。执行器自述完成不能覆盖任务验证状态；对用户先显示已验证产物，内部路由细节保留在执行记录。</p>
      </section>
      <section className="chapter" id="acceptance">
        <div className="tt-pagehead"><h2>分阶段落地与验收</h2><Tag>尚未进入产品实现</Tag></div>
        <div className="three-col"><div><h3>首期：看得清、选得准</h3><ul><li>统一类型、能力与证据视图，补齐附件 8 项映射。</li><li>设置和首页共用能力选择器，支持已保存聚合。</li><li>models CLI 与新启动/任务覆盖；固定覆盖不改默认值。</li><li>Auto 复用现有池和策略，严格免费、能力与协议预检。</li></ul></div><div><h3>下一期：长时任务</h3><ul><li>持久检查点、等待额度、重启恢复与可验证重试。</li><li>轻量步骤评测，按质量与延迟记录选择效果。</li><li>候选失效自动移出运行集，新增免费模型须先验证。</li><li>复杂度分类建立离线验收集后再启用。</li></ul></div><div><h3>产品验收标准</h3><ul><li>Web 与 CLI 同一修订得到相同能力结论。</li><li>图片请求不得落到文本模型；未知不冒充支持。</li><li>任务覆盖不改 Main/Worker，错误不泄漏空会话。</li><li>免费池耗尽持久等待，重启后不重复外部动作。</li><li>桌面四档和安卓真实触控、返回、草稿与安全区通过。</li></ul></div></div>
        <details><summary>本次设计稿证据、来源与仍需确认项</summary><div className="stack"><p>公开快照抓取时间：<code>{evidence.retrievedAt}</code>。仅访问公开模型目录，未提交推理、未读取或修改生产密钥及模型配置。静态设计验收见 <code>acceptance.md</code>；阶段一生产范围与运行验收见 <code>implementation.md</code>、<code>runtime-acceptance.md</code>。</p><p>落地前检查 <code>hy4free</code> 与 <code>workbuddy-hy4</code> 的实际候选图、当前账号能力与费用；不能把历史测试映射当现场事实。图中其余 6 个公开 ID 已核对，但本节点的源、启用状态与协议链路仍待验证。</p><p><a href="model-evidence.json">六个公开模型的原始字段快照</a> · <a href="https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties" target="_blank" rel="noreferrer">Models API 字段</a> · <a href="https://openrouter.ai/docs/guides/routing/routers/free-router" target="_blank" rel="noreferrer">Free Router 的调度语义</a> · <a href="https://openrouter.ai/docs/api_reference/limits" target="_blank" rel="noreferrer">额度与限流</a></p><p>官方说明：Free Router 按请求所需特性筛选免费模型；可用模型变化，属于上游调度。免费速率和账号限制仍生效，本方案不固定写死提供方限额。</p></div></details>
      </section>
      </>}
      <footer className="footnote">Roami / 模型能力与 Auto 调度 · 技术设计与原型设计。HTML 可离线打开；附件和证据使用相对路径。</footer>
    </main></div>
  </div>
}
createRoot(document.getElementById('root')!).render(<App />)
