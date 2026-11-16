import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useLayout } from '../../../frontend/src/layout'
import { HomeIcon, FolderIcon, AppsIcon, GearIcon, ChevronLeft, ChevronDown, CloseIcon, CheckIcon } from '../../../frontend/src/icons'
import { choices, findModel, matches, eligibleMembers, kindLabel, caps, capabilitySummary, type Model } from './prototype-models'
import PrototypeGateway, { initialGatewayKeys } from './prototype-gateway'

const routes = { roami: '/capabilities/agents/roami', agents: '/capabilities/agents', catalog: '/capabilities/models/gateway',
  tools: '/tools', home: '/home', projects: '/projects', task: '/projects/demo-project', settings: '/settings' }
type Page = keyof typeof routes
type Target = 'main' | 'worker' | 'conversation' | 'task'
const targetLabel = { main: '主智能体', worker: '执行智能体', conversation: '当前对话', task: '当前任务' }
const crumbs: Record<Page, string[]> = {
  roami: ['工具', '能力', '智能体', 'Roami'], agents: ['工具', '能力', '智能体'], catalog: ['工具', '能力', '大模型', '本机网关'],
  tools: ['工具'], home: ['首页', '对话'], projects: ['项目'], task: ['项目', '演示项目', '下任务'], settings: ['设置'],
}
const navigation = [
  { page: 'home' as Page, text: '首页', Icon: HomeIcon }, { page: 'projects' as Page, text: '项目', Icon: FolderIcon },
  { page: 'tools' as Page, text: '工具', Icon: AppsIcon }, { page: 'settings' as Page, text: '设置', Icon: GearIcon },
]
function currentPage(): Page {
  const path = location.hash.slice(1)
  return (Object.keys(routes) as Page[]).find(page => routes[page] === path) || 'roami'
}
function Tag({ children }: { children: React.ReactNode }) { return <span className="tag">{children}</span> }
function Back({ onClick, name = '返回' }: { onClick: () => void; name?: string }) {
  return <button type="button" className="quiet iconbutton" aria-label={name} onClick={onClick}><ChevronLeft size={20} /></button>
}
function ModelPicker({ target, value, catalog, onChoose, onClose, onManage }: { target: Target; value: string; catalog: Model[]; onChoose: (id: string) => void; onClose: () => void; onManage: () => void }) {
  const { phone } = useLayout()
  const dialog = useRef<HTMLDialogElement>(null)
  const [query, setQuery] = useState(''), [kind, setKind] = useState('all'), [requirements, setRequirements] = useState<string[]>([])
  useEffect(() => {
    const node = dialog.current!
    node.showModal()
    return () => node.close()
  }, [])
  const filtered = catalog.filter(model => model.configured !== false && (kind === 'all' || model.kind === kind) &&
    (model.name + model.id + model.upstream).toLowerCase().includes(query.toLowerCase()) && matches(model, requirements, catalog))
  return <dialog ref={dialog} className="context-picker" aria-labelledby="picker-title" onCancel={event => { event.preventDefault(); onClose() }}>
    <header className="picker-header">{phone && <Back onClick={onClose} name="返回原页面" />}<h2 id="picker-title">选择{targetLabel[target]}模型</h2>{!phone && <button type="button" className="quiet iconbutton" aria-label="关闭模型选择" onClick={onClose}><CloseIcon size={20} /></button>}</header>
    <div className="picker-controls">
      <p className="meta">当前选择：{findModel(value, catalog).name}</p>
      <div className="filters"><label className="field search">搜索模型<input autoFocus={!phone} placeholder="名称或模型 ID" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label className="field">模型类型<select value={kind} onChange={event => setKind(event.target.value)}><option value="all">全部类型</option><option value="single">具体模型</option><option value="aggregate">Roami 聚合</option><option value="router">上游自动路由</option><option value="unknown">待核对</option></select></label></div>
      <div className="row">{caps.map(([cap, label]) => <label className="check" key={cap}><input type="checkbox" checked={requirements.includes(cap)} onChange={() => setRequirements(values => values.includes(cap) ? values.filter(value => value !== cap) : [...values, cap])} />{label}</label>)}</div>
    </div>
    <div className="picker-options" aria-label="模型列表">
      {filtered.map(model => <button type="button" className="model-option" key={model.id} aria-pressed={value === model.id} onClick={() => onChoose(model.id)}>
        <div className="option-copy"><strong>{model.name}</strong><small>{kindLabel[model.kind]} · {capabilitySummary(model)}</small>
        <small>{model.kind === 'aggregate' ? `${model.members?.length || 0} 个成员 / ${model.freeOnly ? '配置为仅免费' : '沿用聚合定价规则'}` : model.kind === 'unknown' ? '本地映射待核对' : 'OpenRouter / 公开能力声明 / 路径未验证'}</small></div>
        {value === model.id && <CheckIcon size={20} />}
      </button>)}
      {!filtered.length && <div className="picker-empty"><p>没有符合条件的模型。</p><button type="button" onClick={() => { setRequirements([]); setKind('all'); setQuery('') }}>清除筛选</button></div>}
    </div>
    <footer className="picker-footer meta">{target === 'task' ? '只用于这次任务，不更改模型设置。' : target === 'conversation' ? '只用于当前对话。' : '选择后回到 Roami 页面，点击“应用”保存。'}<button type="button" className="quiet" onClick={onManage}>管理网关模型</button></footer>
  </dialog>
}
function App() {
  const { phone } = useLayout()
  const [page, setPage] = useState<Page>(currentPage)
  const [theme, setTheme] = useState('dark')
  const [picker, setPicker] = useState<Target | null>(null)
  const [catalog, setCatalog] = useState<Model[]>(choices)
  const [gatewayKeys, setGatewayKeys] = useState(initialGatewayKeys)
  const [selection, setSelection] = useState<Record<Target, string>>({ main: 'workbuddy-hy4', worker: 'or-lightning-free', conversation: 'workbuddy-hy4', task: 'free-pool' })
  const [saved, setSaved] = useState({ main: 'workbuddy-hy4', worker: 'or-lightning-free' })
  const [notice, setNotice] = useState('')
  const [chat, setChat] = useState('请根据这张截图，整理可用模型及其能力。')
  const [task, setTask] = useState('整理资料并输出结构化清单。')
  const [taskCaps, setTaskCaps] = useState<string[]>(['tools']), [freeOnly, setFreeOnly] = useState(true), [verifiedOnly, setVerifiedOnly] = useState(false)
  const [preview, setPreview] = useState(false)
  const scroll = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const keyboard = (navigator as Navigator & { virtualKeyboard?: { overlaysContent: boolean } }).virtualKeyboard
    if (keyboard) keyboard.overlaysContent = true
    if (!Object.values(routes).includes(location.hash.slice(1))) history.replaceState(null, '', '#' + routes.roami)
    const changed = () => { setPage(currentPage()); setNotice(''); setPicker(null); scroll.current?.scrollTo(0, 0) }
    window.addEventListener('hashchange', changed)
    return () => window.removeEventListener('hashchange', changed)
  }, [])
  const go = (next: Page) => { location.hash = routes[next] }
  const dirty = selection.main !== saved.main || selection.worker !== saved.worker
  const active = ['roami', 'agents', 'catalog', 'tools'].includes(page) ? 'tools' : page === 'task' ? 'projects' : page
  const title = page === 'roami' ? 'Roami 主智能体与执行智能体' : page === 'agents' ? '智能体' : page === 'catalog' ? '本机网关' : page === 'task' ? '演示项目' : navigation.find(item => item.page === page)?.text || '能力'
  const choose = (id: string) => {
    if (!picker) return
    setSelection(values => ({ ...values, [picker]: id }))
    setNotice(picker === 'main' || picker === 'worker' ? '已选择，点击“应用”保存。' : '')
    setPreview(false); setPicker(null)
  }
  const modelButton = (target: Target) => <button type="button" className="model-trigger" aria-label={'选择' + targetLabel[target] + '模型'} aria-haspopup="dialog" onClick={() => setPicker(target)}>
    <span><strong>{findModel(selection[target], catalog).name}</strong><small>{kindLabel[findModel(selection[target], catalog).kind]} · {capabilitySummary(findModel(selection[target], catalog))}</small></span><ChevronDown size={18} />
  </button>
  const back = page === 'roami' ? () => go('agents') : page === 'agents' || page === 'catalog' ? () => go('tools') : page === 'task' ? () => go('projects') : undefined
  const taskPool = findModel(selection.task, catalog)
  const isAggregate = taskPool.kind === 'aggregate'
  const candidates = verifiedOnly ? [] : eligibleMembers(taskPool, taskCaps, catalog, freeOnly)
  return <div className="app context-prototype">
    <div className="prototype-docbar"><span className="meta">{phone ? '交互原型' : '交互原型 · 演示数据，不连接服务'}</span><nav aria-label="设计文档"><a href="technical-design.html">技术设计</a><a href="prototype.html" aria-current="page">原型设计</a></nav><button type="button" className="quiet" onClick={() => { const next = theme === 'dark' ? 'light' : 'dark'; setTheme(next); document.documentElement.dataset.theme = next }}>{theme === 'dark' ? '浅色' : '深色'}</button></div>
    <div className="host-shell">
      {!phone && <aside className="host-sidebar"><div className="host-brand"><strong>Roami</strong><span className="meta">本机</span></div><nav aria-label="主导航">{navigation.map(({ page: next, text, Icon }) => <React.Fragment key={next}><a href={'#' + routes[next]} aria-current={active === next ? 'page' : undefined}><Icon size={20} />{text}</a>{next === 'tools' && <a className="sidebar-capabilities" href={'#' + routes.agents}>能力</a>}</React.Fragment>)}</nav></aside>}
      <div className="host-workspace">
        <header className="host-appbar">{phone && back && <Back onClick={back} />}<h1>{phone ? title : ['roami', 'agents', 'catalog'].includes(page) ? '能力' : title}</h1><span className="meta">{phone ? '演示' : '本机 / 原型'}</span></header>
        <div className="location-strip" aria-label="当前页面位置"><span className="meta">页面位置</span><span>{crumbs[page].join(' / ')}</span></div>
        {!phone && ['roami', 'agents', 'catalog'].includes(page) && <nav className="capability-tabs" aria-label="能力分类"><a href={'#' + routes.catalog} aria-current={page === 'catalog' ? 'page' : undefined}>大模型</a><a href={'#' + routes.agents} aria-current={page !== 'catalog' ? 'page' : undefined}>智能体</a><span>插件</span><span>Skills</span><span>MCP</span><span>CLI</span><span>工具</span><span>市场</span></nav>}
        <div className="model-page-workspace">
          {page === 'catalog' && <nav className="model-section-nav" aria-label="大模型导航">{['模型源','聚合','概况','监控','审计','本机网关','语音输入'].map(label => <span key={label} aria-current={label === '本机网关' ? 'page' : undefined}>{label}</span>)}</nav>}
        <div className="host-scroll" ref={scroll}>
          {page === 'roami' && <section className="role-settings" aria-label="Roami 模型设置">
            {!phone && <div className="tt-pagehead"><div className="heading-with-back"><Back onClick={() => go('agents')} name="返回智能体列表" /><h2>Roami 主智能体与执行智能体</h2></div><Tag>截图对应页面</Tag></div>}
            <p className="meta">主智能体和执行智能体使用同一份模型列表，由 Roami 网关适配上游连接。</p>
            <div className="role-fields">{(['main', 'worker'] as const).map(target => <div className="role-field" key={target}><label>{targetLabel[target]}</label>{modelButton(target)}</div>)}</div>
            <div className="row"><button type="button" className="primary" disabled={!dirty} onClick={() => { setSaved({ main: selection.main, worker: selection.worker }); setNotice('已应用到演示配置。') }}>应用</button><button type="button" disabled={!dirty} onClick={() => { setSelection(value => ({ ...value, ...saved })); setNotice('') }}>取消更改</button></div>
            <p className="notice" role="status">{notice}</p>
            <details><summary>更多设置</summary><p className="meta">能力声明和来源在模型目录中查看。</p><button type="button" onClick={() => go('catalog')}>打开模型目录</button></details>
            <p className="location-explanation">本次修改的是上面两个选择框：点开后可按模型类型、图片输入、工具调用等条件筛选。</p>
          </section>}
          {page === 'agents' && <section className="context-section"><div className="tt-pagehead"><h2>智能体</h2></div><article className="entry-row"><div><strong>Roami</strong><p className="meta">主智能体与执行智能体</p></div><button type="button" onClick={() => go('roami')}>管理</button></article><p className="meta">点击 Roami 的“管理”，进入你截图中的模型设置页。</p></section>}
          {page === 'tools' && <section className="context-section"><div className="tt-pagehead"><h2>工具</h2></div><article className="entry-row"><div><strong>能力</strong><p className="meta">智能体、模型、Skills 与 MCP</p></div><button type="button" onClick={() => go('agents')}>打开</button></article></section>}
          {page === 'settings' && <section className="context-section"><p>模型在“工具 / 能力”中管理。</p><button type="button" onClick={() => go('agents')}>打开能力</button></section>}
          {page === 'catalog' && <PrototypeGateway catalog={catalog} onCatalog={setCatalog} keys={gatewayKeys} onKeys={setGatewayKeys} onRoami={() => go('roami')} />}
          {page === 'home' && <section className="conversation-page"><div className="conversation-content"><p className="meta">当前对话</p><h2>整理模型资料</h2><p>模型选择在对话输入框下方。本页选择只用于当前对话。</p></div><div className="context-composer"><label className="field">消息<textarea value={chat} onChange={event => setChat(event.target.value)} rows={3} /></label><div className="composer-model">{modelButton('conversation')}<button type="button" onClick={() => setNotice('演示内容已保留，没有发送实际请求。')}>预览</button></div><p className="meta" role="status">{notice}</p></div></section>}
          {page === 'projects' && <section className="context-section"><div className="tt-pagehead"><h2>项目</h2></div><article className="entry-row"><div><strong>演示项目</strong><p className="meta">查看下任务时的指定模型与 Auto 选项</p></div><button type="button" onClick={() => go('task')}>打开</button></article></section>}
          {page === 'task' && <section className="task-page"><div className="tt-pagehead"><div className="heading-with-back">{!phone && <Back onClick={() => go('projects')} />}<h2>下任务</h2></div><Tag>拟新增模型选项</Tag></div><div className="context-composer"><label className="field">任务内容<textarea rows={4} value={task} onChange={event => setTask(event.target.value)} /></label><div className="role-field"><label>这次任务使用的模型</label>{modelButton('task')}</div><p className="meta">仅此任务使用，不更改 Roami 的主智能体与执行智能体设置。</p>
            {isAggregate && <div className="task-constraints"><h3>Auto 筛选条件</h3><div className="row">{[['tools', '工具调用'], ['image', '图片输入'], ['schema', 'JSON Schema']].map(([cap, label]) => <label className="check" key={cap}><input type="checkbox" checked={taskCaps.includes(cap)} onChange={() => { setTaskCaps(values => values.includes(cap) ? values.filter(item => item !== cap) : [...values, cap]); setPreview(false) }} />{label}</label>)}</div><div className="row"><label className="check"><input type="checkbox" checked={freeOnly || !!taskPool.freeOnly} disabled={!!taskPool.freeOnly} onChange={event => { setFreeOnly(event.target.checked); setPreview(false) }} />仅免费</label><label className="check"><input type="checkbox" checked={verifiedOnly} onChange={event => { setVerifiedOnly(event.target.checked); setPreview(false) }} />要求已验证</label></div>{taskPool.freeOnly && <p className="meta">该聚合已限制为免费路径，这里的条件只能继续收窄。</p>}</div>}
            <button type="button" className="primary" onClick={() => setPreview(true)}>预览任务</button>
            {preview && <div className="task-preview" role="status"><h3>本次任务计划</h3><p>模型：{findModel(selection.task, catalog).name}</p>{isAggregate ? <><p>{candidates.length ? `${candidates.length} 个模型符合声明条件，实际执行前需验证路径。` : '暂无满足验证要求的模型，任务将等待可用候选。'}</p><ul>{candidates.map(model => <li key={model.id}>{model.name}</li>)}</ul></> : <p>{capabilitySummary(findModel(selection.task, catalog))} / 路径未验证</p>}<p className="meta">这是计划预览，未创建实际任务。</p></div>}
          </div></section>}
        </div></div>
        {phone && <nav className="host-bottomnav" aria-label="主导航">{navigation.map(({ page: next, text, Icon }) => <a href={'#' + routes[next]} key={next} aria-current={active === next ? 'page' : undefined}><Icon size={20} /><span>{text}</span></a>)}</nav>}
      </div>
    </div>
    {picker && <ModelPicker target={picker} value={selection[picker]} catalog={catalog} onChoose={choose} onClose={() => setPicker(null)} onManage={() => { setPicker(null); go('catalog') }} />}
  </div>
}
createRoot(document.getElementById('root')!).render(<App />)
