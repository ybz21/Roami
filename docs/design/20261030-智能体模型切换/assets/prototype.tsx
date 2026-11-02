import React, { useEffect, useLayoutEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Button, ConfigProvider, Input, Modal, Radio, Select, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { THEME_TOKENS } from '../../../../frontend/src/theme'
import { useLayout } from '../../../../frontend/src/layout'
import { AgentLogo, AppsIcon, BotIcon, ChevronLeft, ChevronRight, CloseIcon, FolderIcon, GearIcon, GlobeIcon, HomeIcon, LinkIcon, PlusIcon, SunIcon } from '../../../../frontend/src/icons'
import './prototype.css'

type Protocol = 'responses' | 'messages' | 'chat'
type Source = { id: string; name: string; url: string; protocols: Protocol[] }
type Model = { id: string; name: string; protocol: Protocol; primary: string; backups: string[]; strategy: 'fixed' | 'failover'; published: boolean }
type Kind = 'roami' | 'codex' | 'claude' | 'opencode' | 'pi'
type Choice = { mode: 'original' | 'gateway'; model: string }
type Route = { area: 'models' | 'agents' | 'notes'; tab: 'sources' | 'catalog' | 'usage'; detail?: 'source' | 'model' | 'gateway' | 'agent'; id?: string; from?: string; consumer?: Kind }
const protocols = { responses: 'Responses', messages: 'Messages', chat: 'Chat Completions' }
const names: Record<Kind, string> = { roami: 'Roami', codex: 'Codex', claude: 'Claude Code', opencode: 'OpenCode', pi: 'Pi' }
const initialSources: Source[] = [
  { id: 'work', name: '工作网关', url: 'https://models.example.com', protocols: ['responses', 'messages'] },
  { id: 'router', name: 'OpenRouter', url: 'https://openrouter.ai/api', protocols: ['responses', 'messages'] },
  { id: 'local', name: '本地模型', url: 'http://127.0.0.1:11434', protocols: ['chat'] },
]
const initialModels: Model[] = [
  { id: 'coding-main', name: '编程主力', protocol: 'responses', primary: 'work', backups: ['router'], strategy: 'failover', published: true },
  { id: 'claude-main', name: 'Claude 主力', protocol: 'messages', primary: 'work', backups: [], strategy: 'fixed', published: true },
]
const initialChoices: Record<Kind, Choice> = {
  roami: { mode: 'gateway', model: 'coding-main' }, codex: { mode: 'original', model: 'coding-main' },
  claude: { mode: 'gateway', model: 'claude-main' }, opencode: { mode: 'original', model: 'coding-main' }, pi: { mode: 'original', model: 'coding-main' },
}
const navigation = [{ name: '首页', icon: HomeIcon }, { name: '项目', icon: FolderIcon }, { name: '工具', icon: AppsIcon }, { name: '设置', icon: GearIcon }]
function go(path: string) { location.hash = '/' + path }
function readRoute(): Route {
  const [path, query = ''] = location.hash.replace(/^#\/?/, '').split('?')
  const [area, tab, detail, id] = path.split('/')
  const params = new URLSearchParams(query), from = params.get('from') || ''
  const safeFrom = /^(models\/(sources|catalog)(\/(model|source)\/[a-z0-9-]+)?|agents\/[a-z]+)$/.test(from) ? from : undefined
  if (area === 'notes') return { area: 'notes', tab: 'sources' }
  if (area === 'agents') return { area, tab: 'sources', detail: tab in names ? 'agent' : undefined, id: tab in names ? tab : undefined, from: safeFrom }
  return { area: 'models', tab: ['sources', 'catalog', 'usage'].includes(tab) ? tab as Route['tab'] : 'sources',
    detail: ['source', 'model', 'gateway'].includes(detail) ? detail as Route['detail'] : undefined,
    id, from: safeFrom, consumer: params.get('consumer') in names ? params.get('consumer') as Kind : undefined }
}
function Mark({ kind }: { kind: Kind }) { return kind === 'claude' || kind === 'codex' ? <AgentLogo kind={kind} size={24} /> : <BotIcon size={24} /> }
function App() {
  const layout = useLayout()
  const [route, setRoute] = useState(readRoute)
  const [themeMode, setThemeMode] = useState<'dark' | 'light'>('dark')
  const [scenario, setScenario] = useState('normal')
  const [sources, setSources] = useState(initialSources), [models, setModels] = useState(initialModels)
  const [choices, setChoices] = useState(initialChoices), [choiceDrafts, setChoiceDrafts] = useState<Partial<Record<Kind, Choice>>>({})
  const [workers, setWorkers] = useState('coding-main'), [workerDraft, setWorkerDraft] = useState('coding-main')
  const [installed, setInstalled] = useState<Record<Kind, boolean>>({ roami: true, codex: true, claude: true, opencode: true, pi: false })
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, Source>>({})
  const [drafts, setDrafts] = useState<Record<string, Model>>({})
  const [notice, setNotice] = useState(''), [preview, setPreview] = useState('')
  const [confirmation, setConfirmation] = useState<'publish' | 'apply' | 'source' | null>(null)
  const id = route.id || 'new', kind = route.id as Kind
  const emptySource: Source = { id: 'new-source', name: '', url: '', protocols: ['responses'] }
  const source = sourceDrafts[id] || sources.find(item => item.id === id) || emptySource
  const newModel: Model = { id: '', name: '', protocol: route.consumer === 'claude' ? 'messages' : 'responses', primary: 'work', backups: [], strategy: 'fixed', published: false }
  const model = drafts[id] || models.find(item => item.id === id) || newModel
  const choice = choiceDrafts[kind] || choices[kind] || initialChoices.codex
  const allowed = (item: Model, target: Kind) => item.published && (target === 'codex' ? item.protocol === 'responses' : target === 'claude' ? item.protocol === 'messages' : true)
  const optionsFor = (target: Kind) => models.filter(item => allowed(item, target)).map(item => ({ value: item.id, label: item.name }))
  const sourceName = (key: string) => sources.find(item => item.id === key)?.name || key
  const modelName = (key: string) => models.find(item => item.id === key)?.name || key
  const using = (key: string) => (Object.keys(names) as Kind[]).filter(target => choices[target].mode === 'gateway' && (choices[target].model === key || target === 'roami' && workers === key))
  const compatibleSources = sources.filter(item => item.protocols.includes(model.protocol))
  const validModel = !!model.name.trim() && /^[a-z][a-z0-9-]{1,47}$/.test(model.id) &&
    !models.some(item => item.id === model.id && item.id !== id) && compatibleSources.some(item => item.id === model.primary) &&
    (model.strategy === 'fixed' || model.backups.length > 0 && model.backups.every(key => key !== model.primary && compatibleSources.some(item => item.id === key)))
  const changed = JSON.stringify(model) !== JSON.stringify(models.find(item => item.id === id))
  const updateModel = (change: Partial<Model>) => { setDrafts(previous => ({ ...previous, [id]: { ...model, ...change } })); setPreview('') }
  const updateSource = (change: Partial<Source>) => setSourceDrafts(previous => ({ ...previous, [id]: { ...source, ...change } }))
  const agentPath = (target: Kind, origin?: string) => `agents/${target}${origin ? '?from=' + encodeURIComponent(origin) : ''}`
  const currentPath = route.area === 'agents' ? `agents/${kind}` : `models/${route.tab}${route.detail && id !== 'new' ? '/' + route.detail + '/' + id : ''}`
  const back = () => go(route.from || (route.area === 'agents' ? 'agents' : 'models/' + route.tab))
  useEffect(() => { const change = () => { setRoute(readRoute()); setPreview(''); setConfirmation(null) }; window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change) }, [])
  useLayoutEffect(() => {
    Object.entries(THEME_TOKENS[themeMode].css).forEach(([key, value]) => document.documentElement.style.setProperty(key, value))
    document.documentElement.dataset.theme = themeMode; document.documentElement.style.colorScheme = themeMode
    document.documentElement.style.setProperty('--accent-solid', antdTheme.getDesignToken({ algorithm: themeMode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm, token: { colorPrimary: THEME_TOKENS.dark.css['--accent'] } }).colorPrimary)
  }, [themeMode])
  const apply = () => { if (kind === 'roami') setWorkers(workerDraft); setChoices(previous => ({ ...previous, [kind]: choice })); setConfirmation(null); setNotice(choice.mode === 'gateway' ? `${names[kind]} 默认模型已设为${modelName(choice.model)}。外部工具重新打开后使用。` : `${names[kind]} 已恢复接管前的模型配置。`) }
  const publish = () => {
    if (!validModel) return
    const next = { ...model, published: true }
    setModels(previous => [...previous.filter(item => item.id !== next.id), next]); setDrafts(previous => ({ ...previous, [next.id]: next }))
    setConfirmation(null); setNotice(`已发布${model.name}。后续新请求使用新策略，进行中的请求保持原路由。`)
    if (id === 'new') go(`models/catalog/model/${model.id}${route.from ? '?from=' + encodeURIComponent(route.from) : ''}`)
  }
  const previewRoute = () => {
    if (scenario === 'streaming') setPreview('已开始输出：保持原路由，不自动换源或重放。请恢复当前请求。')
    else if (scenario === 'offline') setPreview(model.strategy === 'failover' && model.backups.length ? `主源连接未建立，尚未提交请求；模拟改用${sourceName(model.backups[0])}。` : '主源连接未建立，未配置备用来源；本次请求不发送。')
    else setPreview(`新请求使用${sourceName(model.primary)}。没有发生故障，备用来源不接收请求。`)
  }
  const saveSource = () => {
    try { const address = new URL(source.url); if (!['http:', 'https:'].includes(address.protocol)) throw new Error() }
    catch { setNotice('请填写有效的 HTTP 或 HTTPS 地址。'); return }
    const next = { ...source, id: id === 'new' ? 'source-' + (sources.length + 1) : id }
    setSources(previous => [...previous.filter(item => item.id !== next.id), next]); setConfirmation(null); setNotice('模型源已保存为演示数据；尚未验证真实连接。'); go('models/sources')
  }
  const theme = { algorithm: themeMode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: { colorPrimary: THEME_TOKENS.dark.css['--accent'], colorBgBase: THEME_TOKENS[themeMode].css['--bg-base'], colorBgContainer: THEME_TOKENS[themeMode].css['--bg-container'], borderRadius: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--r-xs')), fontSize: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fs-body')) } }
  const detailTitle = route.detail === 'agent' ? names[kind] : route.detail === 'gateway' ? '统一接入' : route.detail === 'source' ? id === 'new' ? '添加模型源' : source.name : id === 'new' ? '新建对外模型' : model.name
  const agentDetail = <>
    <div className="current"><span>开发主机</span><strong>{kind === 'roami' ? '内置智能体' : installed[kind] ? '已安装' : '未安装'}</strong><small>{kind === 'roami' ? '主智能体与执行智能体分别选模' : '安装、登录、启动和模型在此统一管理'}</small></div>
    {kind !== 'roami' && <div className="lifecycle"><Button onClick={() => { setInstalled(previous => ({ ...previous, [kind]: true })); setNotice('演示：安装与升级由现有智能体管理流程承接。') }}>{installed[kind] ? '升级' : '安装'}</Button><Button disabled={!installed[kind]} onClick={() => setNotice('演示：在此工具中继续登录，不导出订阅凭据。')}>登录</Button><Button disabled={!installed[kind]} onClick={() => setNotice('演示：从当前节点启动此智能体。')}>启动</Button></div>}
    <h3 className="block-title">模型</h3>
    {kind !== 'roami' && <Radio.Group className="choice-stack" value={choice.mode} onChange={event => setChoiceDrafts(previous => ({ ...previous, [kind]: { ...choice, mode: event.target.value } }))}><Radio value="original">使用原配置</Radio><Radio value="gateway">使用 Roami 大模型</Radio></Radio.Group>}
    {(kind === 'roami' || choice.mode === 'gateway') && <>
      <label className="field">{kind === 'roami' ? '主智能体' : '对外模型'}<Select id="agent-model" aria-label="对外模型" value={choice.model} options={optionsFor(kind)} onChange={value => setChoiceDrafts(previous => ({ ...previous, [kind]: { mode: 'gateway', model: value } }))} /></label>
      {kind === 'roami' && <label className="field">执行智能体<Select aria-label="执行智能体模型" value={workerDraft} options={optionsFor(kind)} onChange={setWorkerDraft} /></label>}
      <div className="binding-path"><LinkIcon size={18} /><span>统一接入 / {modelName(choice.model)}</span></div>
      <p className="hint">只选择对外模型，无需填写上游地址与密钥。</p>
      <button type="button" className="text-action" id="manage-policy" onClick={() => go(`models/catalog/model/${choice.model}?from=${encodeURIComponent(agentPath(kind))}`)}>管理此模型的来源与策略<ChevronRight size={16} /></button>
      <button type="button" className="text-action" onClick={() => go(`models/catalog/model/new?consumer=${kind}&from=${encodeURIComponent(agentPath(kind))}`)}>添加对外模型</button>
    </>}
    {kind !== 'roami' && <p className="hint scope-text">应用将修改开发主机上此用户的工具默认配置，包含本机 CLI；不会自动重启当前任务。</p>}
    {scenario === 'conflict' && kind !== 'roami' && <div className="feedback warn">配置在外部发生变化，请先读取并处理差异。<Button onClick={() => { setScenario('normal'); setNotice('演示：已读取最新配置，选择保留；现在可重新应用。') }}>读取当前配置</Button></div>}
    <div className="apply-actions"><Button onClick={back}>{route.from ? '返回大模型' : '返回'}</Button><Button type="primary" id="apply-agent" disabled={!installed[kind] || scenario === 'conflict' || choice.mode === 'gateway' && !models.some(item => item.id === choice.model && allowed(item, kind))} onClick={() => kind === 'roami' ? apply() : setConfirmation('apply')}>应用</Button></div>
  </>
  const modelDetail = <>
    <label className="field">名称<Input id="model-name" value={model.name} placeholder="例如：编程主力" onChange={event => updateModel({ name: event.target.value })} /></label>
    <label className="field">对外标识<Input id="public-id" value={model.id} readOnly={id !== 'new'} placeholder="例如：coding-main" onChange={event => updateModel({ id: event.target.value })} /></label>
    <label className="field">协议<Select aria-label="模型协议" value={model.protocol} disabled={id !== 'new'} options={Object.entries(protocols).map(([value, label]) => ({ value, label }))} onChange={protocol => updateModel({ protocol, backups: [], primary: sources.find(item => item.protocols.includes(protocol))?.id || '' })} /></label>
    <label className="field">主模型源<Select id="primary-source" aria-label="主模型源" value={model.primary} options={sources.map(item => ({ value: item.id, label: item.name + (item.protocols.includes(model.protocol) ? '' : '（协议不兼容）'), disabled: !item.protocols.includes(model.protocol) }))} onChange={primary => updateModel({ primary, backups: model.backups.filter(item => item !== primary) })} /></label>
    <details className="technical"><summary>真实模型映射</summary><p>主模型：{model.protocol === 'messages' ? 'Claude 编程模型' : 'Coding Pro'}（演示）</p><p>备用需验证模型身份、协议、工具与上下文能力一致。</p></details>
    <label className="field">聚合策略<Select id="routing-strategy" aria-label="聚合策略" value={model.strategy} options={[{ value: 'fixed', label: '固定来源' }, { value: 'failover', label: '主备切换' }]} onChange={strategy => updateModel({ strategy })} /></label>
    {model.strategy === 'failover' && <label className="field">备用模型源<Select id="backup-sources" mode="multiple" aria-label="备用模型源" value={model.backups} options={sources.filter(item => item.id !== model.primary).map(item => ({ value: item.id, label: item.name + (item.protocols.includes(model.protocol) ? '' : '（协议不兼容）'), disabled: !item.protocols.includes(model.protocol) }))} onChange={backups => updateModel({ backups })} /><small>按选择顺序尝试；已经输出或状态未知时不重放。</small></label>}
    <div className="testing"><Button id="preview-route" disabled={!validModel} onClick={previewRoute}>预览路由</Button><small>规则模拟，不发送模型请求。</small></div>
    {preview && <div className="feedback" id="route-result" role="status">{preview}</div>}
    <div className="impact"><h3>正在使用</h3><p>{using(model.id).map(target => names[target]).join('、') || '还没有智能体使用'}</p></div>
    <div className="apply-actions"><Button id="save-draft" disabled={!validModel} onClick={() => { setDrafts(previous => ({ ...previous, [id]: model })); setNotice('草稿已保存，运行中的发布版本不变。') }}>保存草稿</Button><Button id="publish-model" type="primary" disabled={!validModel || !changed} onClick={() => setConfirmation('publish')}>发布</Button></div>
    <p className="hint">只有已发布的模型可供智能体选用。</p>
    {route.from?.startsWith('agents/') && <Button className="return-context" onClick={() => { const target = route.from!.split('/')[1] as Kind; if (models.some(item => item.id === model.id && allowed(item, target))) setChoiceDrafts(previous => ({ ...previous, [target]: { mode: 'gateway', model: model.id } })); back() }}>返回并继续配置智能体</Button>}
  </>
  const sourceDetail = <>
    <label className="field">模型源名称<Input aria-label="模型源名称" value={source.name} onChange={event => updateSource({ name: event.target.value })} /></label>
    <label className="field">上游地址<Input aria-label="上游地址" value={source.url} onChange={event => updateSource({ url: event.target.value })} placeholder="https://models.example.com" /></label>
    <label className="field">上游密钥<Input.Password aria-label="上游密钥" placeholder={id === 'new' ? '填写上游 Key（本页不保存真实密钥）' : '密钥已保存，留空保持'} autoComplete="new-password" /></label>
    <label className="field">协议<Select mode="multiple" aria-label="上游协议" value={source.protocols} options={Object.entries(protocols).map(([value, label]) => ({ value, label }))} onChange={value => updateSource({ protocols: value })} /></label>
    <details className="technical"><summary>多个协议端点</summary><p>不同协议可分别配置入口与认证，不能只替换 URL。</p>{source.protocols.map(protocol => <label className="field" key={protocol}>{protocols[protocol]} 地址<Input aria-label={protocols[protocol] + ' 地址'} placeholder="使用此协议的独立上游入口" /></label>)}</details>
    <Button onClick={() => setNotice('演示目录：Coding Pro 与 Claude 编程模型。目录可读不代表模型已验证。')}>读取模型目录</Button><p className="hint scope-text">密钥仅留在模型源；客户端使用独立接入凭据。</p>
    <div className="apply-actions"><Button onClick={back}>取消</Button><Button onClick={() => setNotice('模型源草稿已保存，正式连接未改动。')}>保存草稿</Button><Button id="save-source" type="primary" disabled={!source.name.trim() || !source.url.trim() || !source.protocols.length} onClick={() => setConfirmation('source')}>应用</Button></div>
  </>
  const gatewayDetail = <>
    <div className="current"><span>开发主机</span><strong>Roami 统一模型接入</strong><small>一个接入，多个上游，共用对外模型目录。</small></div>
    <dl><dt>访问范围</dt><dd>本机回环</dd><dt>服务状态</dt><dd>已启动（演示）</dd><dt>Responses</dt><dd><code>http://127.0.0.1:18700/v1</code></dd><dt>Messages</dt><dd><code>http://127.0.0.1:18700/anthropic</code></dd><dt>调用凭据</dt><dd>由 Roami 为使用方发放，与上游 Key 分离。</dd></dl>
    <p className="hint scope-text">外部客户端复制协议入口并使用接入凭据；LAN 访问需单独配置。这里的端口仅作设计示例。</p>
    <h3 className="block-title">接入智能体</h3><p className="hint">在对应智能体里选择对外模型，由 Roami 完成配置。</p><Button id="gateway-to-agents" onClick={() => go('agents')}>配置智能体</Button>
  </>
  const detailContent = route.detail === 'agent' ? agentDetail : route.detail === 'model' ? modelDetail : route.detail === 'source' ? sourceDetail : gatewayDetail
  const consumers = <section className="consumers"><div className="section-head"><h3>正在使用</h3><Button id="configure-agents" onClick={() => go('agents')}>配置智能体</Button></div>{(Object.keys(names) as Kind[]).filter(target => choices[target].mode === 'gateway').map(target => <div className="consumer-row" key={target}><Mark kind={target} /><div><strong>{names[target]}</strong><small>{modelName(choices[target].model)}</small></div><button type="button" className="quiet-button" onClick={() => go(agentPath(target, 'models/' + route.tab))}>配置</button></div>)}</section>
  const modelsOverview = <>
    <div className="gateway-summary"><LinkIcon size={22} /><div><strong>统一接入</strong><small>开发主机 · 本机可用 · 演示状态</small></div><Button id="gateway-details" onClick={() => go(`models/${route.tab}/gateway/local`)}>接入说明</Button></div>
    <nav className="tabs" aria-label="大模型分类">{(['sources', 'catalog', 'usage'] as const).map(tab => <button type="button" key={tab} aria-current={route.tab === tab ? 'page' : undefined} onClick={() => go('models/' + tab)}>{({ sources: '模型源', catalog: '对外模型', usage: '用量' })[tab]}</button>)}</nav>
    {route.tab === 'sources' ? <><div className="section-head"><h3>上游模型源</h3><Button id="add-source" icon={<PlusIcon size={16} />} onClick={() => go('models/sources/source/new')}>添加</Button></div>{sources.map(item => <div className="connection-row" key={item.id}><div className="row-identity"><GlobeIcon size={24} /><div><strong>{item.name}</strong><small>{new URL(item.url).hostname}</small><div className="usage-pills">{item.protocols.map(protocol => <span key={protocol}>{protocols[protocol]}</span>)}</div></div></div><Button onClick={() => go('models/sources/source/' + item.id)}>管理</Button></div>)}<div className="next-step"><span>添加来源后，建立供智能体选择的对外模型。</span><Button id="next-models" onClick={() => go('models/catalog')}>配置对外模型</Button></div></>
      : route.tab === 'catalog' ? <><div className="section-head"><h3>已发布模型</h3><Button id="add-model" icon={<PlusIcon size={16} />} onClick={() => go('models/catalog/model/new')}>新建</Button></div>{models.map(item => <div className="connection-row" key={item.id}><div className="row-identity"><BotIcon size={24} /><div><strong>{item.name}</strong><small>{item.id} · 已发布</small><p className="hint">{sourceName(item.primary)}{item.strategy === 'failover' ? ` · 备用 ${item.backups.map(sourceName).join('、')}` : ' · 固定来源'}</p><div className="usage-pills">{using(item.id).map(target => <span key={target}>{names[target]}</span>)}</div></div></div><Button id={'edit-' + item.id} onClick={() => go('models/catalog/model/' + item.id)}>配置</Button></div>)}</>
        : <><div className="section-head"><h3>按真实请求记账</h3></div><div className="usage-example"><span>使用方</span><span>对外模型</span><span>实际来源</span><strong>Codex</strong><strong>编程主力</strong><strong>工作网关</strong><small>演示记录</small><small>已完成</small><small>用量已确认</small></div><p className="hint scope-text">此处承接现有用量、模型单价和每日金额限额。未经过统一接入的官方登录调用不纳入本地统计。</p></>}
    {route.tab !== 'usage' && consumers}
  </>
  const agentsOverview = <><div className="section-head"><div><h3>安装、登录与模型，一处管理</h3><p className="hint">这里是能力中唯一的智能体目录。</p></div></div>{(Object.keys(names) as Kind[]).map(target => <div className="agent-row" key={target}><div className="row-identity"><Mark kind={target} /><div><strong>{names[target]}</strong><small>{target === 'roami' ? '内置' : installed[target] ? '已安装' : '未安装'}</small></div></div><div className="row-model"><strong>{choices[target].mode === 'gateway' ? modelName(choices[target].model) : '使用原配置'}</strong><small>{choices[target].mode === 'gateway' ? 'Roami 统一接入' : '工具原有连接与登录'}</small></div><Button id={'agent-' + target} onClick={() => go(agentPath(target))}>配置</Button></div>)}</>
  const notes = <article className="notes"><h2>统一到能力，分成相邻两页</h2><h3>Product Design</h3><p>大模型管理一个节点接入、多个上游模型源、稳定对外模型和聚合策略；智能体管理安装、登录、启动和选模。</p><div className="architecture"><span>多个上游模型源</span><ChevronRight size={20} /><span>统一接入与对外模型</span><ChevronRight size={20} /><span>智能体与其它客户端</span></div><h3>为什么不放同一个长页面</h3><p>两者在同一个能力中心，配置顺序相连；日常管理各有入口。大模型下方列使用方摘要，点击进入同一智能体详情，不复制第二套配置。</p><h3>User Stories</h3><p>添加来源、建编程主力、设主备、发布、给 Codex 选择；日常换源只发布模型策略。需要安装和登录时留在智能体详情。</p><h3>Technical Design</h3><p>一个 Go 网关、多个源、可发布的模型映射与策略、智能体绑定。原生配置只持网关入口和调用凭据，原有模型配置迁移并保留恢复。</p><h3>生效与异常</h3><p>接入工具更新默认配置；发布策略影响后续请求。已经输出、工具执行状态或费用未知时不自动重放；供应商续接上下文不能直接迁往另一来源。</p><h3>原型边界</h3><p>所有来源、端口、模型、安装、发布与路由预览都是模拟，页面不调用产品 API。中文为内部评审稿；完整规则和迁移见同目录 README。</p><Button onClick={() => go('models/sources')}>体验完整流程</Button></article>
  return <ConfigProvider locale={zhCN} theme={theme}>
    <div className="design-bar"><span><b>第二版 · 能力中心</b><span className="demo-label">演示数据，不改本机配置</span></span><div className="design-controls"><Select aria-label="演示场景" value={scenario} options={[{ value: 'normal', label: '正常请求' }, { value: 'offline', label: '主源未连上' }, { value: 'streaming', label: '已经输出' }, { value: 'conflict', label: '配置冲突' }]} onChange={value => { setScenario(value); setPreview(''); if (value === 'conflict') go('agents/codex'); else if (value !== 'normal') go('models/catalog/model/coding-main') }} /><button type="button" className="icon-button" aria-label="切换主题" onClick={() => setThemeMode(value => value === 'dark' ? 'light' : 'dark')}><SunIcon size={20} /></button><Button id="design-notes" onClick={() => go(route.area === 'notes' ? 'models/sources' : 'notes')}>{route.area === 'notes' ? '查看原型' : '方案说明'}</Button></div></div>
    <div className="app-shell">{layout.desktop && <nav className="main-nav" aria-label="主导航"><strong className="wordmark">Roami</strong>{navigation.map(item => <div className={'nav-item' + (item.name === '工具' ? ' selected' : '')} key={item.name}><item.icon size={20} /><span>{item.name}</span></div>)}<div className="nav-bottom"><span className="node-dot" />开发主机</div></nav>}
      <div className="workspace"><header className="workspace-head">{route.detail ? <button type="button" id="detail-back" className="icon-button" aria-label="返回" onClick={back}><ChevronLeft size={20} /></button> : null}<strong>{layout.phone && route.detail ? detailTitle : '能力'}</strong><span className="node"><span className="node-dot" />开发主机</span></header>
        {!route.detail || layout.size === 'large' ? <nav className="capability-tabs" aria-label="能力分类">{layout.phone ? <Select aria-label="能力分类" value={route.area === 'agents' ? 'agents' : 'models'} options={[{ value: 'models', label: '大模型' }, { value: 'agents', label: '智能体' }]} onChange={value => go(value === 'models' ? 'models/sources' : 'agents')} /> : <>{[{ key: 'models', label: '大模型' }, { key: 'agents', label: '智能体' }].map(item => <button type="button" key={item.key} aria-current={route.area === item.key ? 'page' : undefined} onClick={() => go(item.key === 'models' ? 'models/sources' : 'agents')}>{item.label}</button>)}<span className="other-capabilities">插件　技能　MCP　CLI　工具　市场</span></>}</nav> : null}
        {notice && <div className="global-notice" role="status"><span>{notice}</span><button type="button" aria-label="关闭提示" className="icon-button" onClick={() => setNotice('')}><CloseIcon size={18} /></button></div>}
        <main className="main-area">{route.area === 'notes' ? notes : <>{(!route.detail || layout.size === 'large') && <div className="overview-pane"><div className="page-scroll">{layout.desktop && <div className="tt-pagehead"><h2>{route.area === 'models' ? '大模型' : '智能体'}</h2></div>}<div className="overview-content">{route.area === 'models' ? modelsOverview : agentsOverview}</div></div></div>}{route.detail && <section className="detail-pane" aria-label={detailTitle} key={route.detail + id}>{layout.size === 'large' && <div className="detail-head"><h3>{detailTitle}</h3><button type="button" className="quiet-button" onClick={back}>{route.from ? '返回来源' : '返回'}</button></div>}<div className="detail-scroll">{detailContent}</div></section>}</>}</main>
        {layout.phone && !layout.keyboard && <nav className="bottom-nav" aria-label="主导航">{navigation.map(item => <button type="button" key={item.name} aria-current={item.name === '工具' ? 'page' : undefined} onClick={() => item.name === '工具' ? go('models/sources') : setNotice(`演示原型：${item.name}仍是原有主导航。`)}><item.icon size={22} /><span>{item.name}</span></button>)}</nav>}
      </div>
    </div>
    <Modal open={!!confirmation} centered title={confirmation === 'source' ? '应用模型源配置？' : confirmation === 'publish' ? `发布${model.name}？` : choice.mode === 'gateway' ? `接入 ${names[kind]}？` : '恢复原配置？'} onCancel={() => setConfirmation(null)} footer={<><Button onClick={() => setConfirmation(null)}>取消</Button><Button id="confirm-action" type="primary" onClick={confirmation === 'source' ? saveSource : confirmation === 'publish' ? publish : apply}>{confirmation === 'source' ? '应用' : confirmation === 'publish' ? '发布' : choice.mode === 'gateway' ? '应用并备份' : '恢复'}</Button></>}>
      {confirmation === 'source' ? <><p>影响对外模型：{models.filter(item => item.primary === id || item.backups.includes(id)).map(item => item.name).join('、') || '尚无引用'}。</p><p className="hint">正式接入需先验证连接；本次仅应用演示数据。</p></> : confirmation === 'publish' ? <><p>影响使用方：{using(model.id).map(target => names[target]).join('、') || '尚无使用方'}。</p><p className="hint">后续新请求使用新策略；进行中的请求和绑定上下文保持原路由。</p></> : <><p>修改开发主机上此用户的默认模型配置，包含本机 CLI。</p><p className="hint">不会自动重启当前任务；首次接入保留原配置备份。</p></>}
    </Modal>
  </ConfigProvider>
}
createRoot(document.getElementById('root')!).render(<App />)
