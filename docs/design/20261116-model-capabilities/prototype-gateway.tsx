import React, { useEffect, useRef, useState } from 'react'
import { useLayout } from '../../../frontend/src/layout'
import { ChevronLeft, CloseIcon, CopyIcon, PlusIcon, MoreIcon } from '../../../frontend/src/icons'
import { type Model, caps, kindLabel, capabilitySummary, matches, findModel } from './prototype-models'

export type GatewayKey = { id: string; name: string; suffix: string; enabled: boolean; fixed?: boolean }
export const initialGatewayKeys: GatewayKey[] = [
  { id: 'development', name: 'Development', suffix: '7c2a', enabled: true },
  { id: 'codex', name: 'Codex CLI', suffix: '9e41', enabled: true },
  { id: 'staging', name: 'Staging', suffix: 'b30f', enabled: false },
]
type Props = { catalog: Model[]; onCatalog: React.Dispatch<React.SetStateAction<Model[]>>;
  keys: GatewayKey[]; onKeys: React.Dispatch<React.SetStateAction<GatewayKey[]>>; onRoami: () => void }
type Panel = { kind: 'model' | 'pool' | 'source' | 'create' | 'rename' | 'fixed' | 'issued'; id?: string }
const directoryTabs = [['configured', '已接入模型'], ['pools', '聚合模型'], ['upstream', '上游目录']]
const endpoint = 'http://127.0.0.1:41155/v1'

function Inspector({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const { phone } = useLayout()
  const dialog = useRef<HTMLDialogElement>(null), aside = useRef<HTMLElement>(null)
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    if (phone) dialog.current?.showModal(); else aside.current?.focus({ preventScroll: true })
    return () => { dialog.current?.close(); opener?.focus({ preventScroll: true }) }
  }, [phone])
  const content = <><header className="gw-panel-head"><button type="button" className="quiet iconbutton" aria-label="返回网关" onClick={onClose}><ChevronLeft size={20} /></button><h2>{title}</h2>{!phone && <button type="button" className="quiet iconbutton" aria-label="关闭详情" onClick={onClose}><CloseIcon size={18} /></button>}</header>{children}</>
  return phone ? <dialog ref={dialog} className="gw-phone-panel" aria-label={title} onCancel={event => { event.preventDefault(); onClose() }}>{content}</dialog>
    : <aside ref={aside} tabIndex={-1} className="gw-inspector" aria-label={title} onKeyDown={event => { if (event.key === 'Escape') onClose() }}>{content}</aside>
}
export default function PrototypeGateway({ catalog, onCatalog, keys, onKeys, onRoami }: Props) {
  const { phone } = useLayout()
  const [tab, setTab] = useState('access'), [directoryTab, setDirectoryTab] = useState('configured')
  const [filters, setFilters] = useState<Record<string, { query: string; source: string; cap: string }>>({})
  const [sampleId, setSampleId] = useState('free-pool'), [language, setLanguage] = useState('curl'), [sampleOpen, setSampleOpen] = useState(false)
  const [panel, setPanel] = useState<Panel | null>(null), [menu, setMenu] = useState<string | null>(null)
  const [nameDraft, setNameDraft] = useState(''), [renameDraft, setRenameDraft] = useState(''), [fixedDraft, setFixedDraft] = useState('')
  const [issued, setIssued] = useState(''), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const [confirmation, setConfirmation] = useState<{ kind: 'disable' | 'rotate' | 'delete' | 'replace'; id: string } | null>(null)
  const confirm = useRef<HTMLDialogElement>(null)
  const [poolDraft, setPoolDraft] = useState<Model | null>(null)
  useEffect(() => { if (confirmation) confirm.current?.showModal() }, [confirmation])
  const filter = filters[directoryTab] || { query: '', source: '', cap: '' }
  const updateFilter = (patch: Partial<typeof filter>) => setFilters(value => ({ ...value, [directoryTab]: { ...filter, ...patch } }))
  const close = () => { setPanel(null); setIssued(''); setFixedDraft(''); setError('') }
  const changeTab = (next: string) => { setTab(next); close(); setMenu(null); setNotice('') }
  const open = (next: Panel) => { setIssued(''); setError(''); setMenu(null); if (next.kind === 'rename') setRenameDraft(keys.find(row => row.id === next.id)?.name || ''); setPanel(next) }
  const copy = async (value: string) => {
    try { await navigator.clipboard.writeText(value); setNotice('已复制。') }
    catch { setNotice('复制失败，请在详情中选中文本复制。') }
  }
  const available = catalog.filter(model => model.configured !== false)
  const sample = available.find(model => model.id === sampleId) || available[0]
  const selected = catalog.find(model => model.id === panel?.id)
  const rows = catalog.filter(model => (directoryTab === 'pools' ? model.kind === 'aggregate' : directoryTab === 'upstream' ? model.configured === false : model.configured !== false && model.kind !== 'aggregate') &&
    (model.name + model.upstream + model.id).toLowerCase().includes(filter.query.toLowerCase()) &&
    (!filter.source || (model.sourceId || 'unverified') === filter.source) && (!filter.cap || matches(model, [filter.cap], catalog)))
  const code = language === 'curl' ? `curl ${endpoint}/chat/completions \\\n+  -H "Authorization: Bearer $ROAMI_GATEWAY_KEY" \\\n+  -H "Content-Type: application/json" \\\n+  -d '{"model":"${sample?.id || ''}","messages":[{"role":"user","content":"Hello"}]}'`
    : `import os\nfrom openai import OpenAI\n\nclient = OpenAI(base_url="${endpoint}",\n                api_key=os.environ["ROAMI_GATEWAY_KEY"])\nresponse = client.chat.completions.create(\n    model="${sample?.id || ''}",\n    messages=[{"role": "user", "content": "Hello"}])`
  const createCredential = (id: string, keyName: string, fixed = false) => {
    const demo = fixed ? fixedDraft : ['DEMO', 'NOT_A_REAL_KEY', String(Date.now())].join('_')
    onKeys(previous => [...previous.filter(row => row.id !== id), { id, name: keyName, suffix: demo.slice(-4), enabled: true, fixed }])
    setIssued(demo); setPanel({ kind: 'issued', id }); setError('')
  }
  const saveKey = (event: React.FormEvent) => {
    event.preventDefault()
    if (panel?.kind === 'fixed') {
      if (fixedDraft.trim().length < 16) { setError('请输入至少 16 个字符的演示值。'); return }
      if (keys.some(row => row.fixed)) { setConfirmation({ kind: 'replace', id: 'fixed' }); return }
      createCredential('fixed', '固定 Key', true)
    } else if (panel?.kind === 'rename') {
      if (!renameDraft.trim()) { setError('请填写名称。'); return }
      onKeys(previous => previous.map(row => row.id === panel.id ? { ...row, name: renameDraft.trim() } : row)); close()
    } else {
      if (!nameDraft.trim()) { setError('请填写名称。'); return }
      createCredential('demo-' + Date.now(), nameDraft.trim()); setNameDraft('')
    }
  }
  const confirmAction = () => {
    if (confirmation?.kind === 'replace') { createCredential('fixed', '固定 Key', true); setConfirmation(null); return }
    const row = keys.find(item => item.id === confirmation?.id)
    if (!row || !confirmation) return
    if (confirmation.kind === 'rotate') createCredential(row.id, row.name, false)
    else onKeys(previous => confirmation.kind === 'delete' ? previous.filter(item => item.id !== row.id) : previous.map(item => item.id === row.id ? { ...item, enabled: false } : item))
    setConfirmation(null); setMenu(null)
  }
  const showExample = (id: string) => { setSampleId(id); setSampleOpen(true); changeTab('access') }
  return <div className="unified-gateway">
    <div className="gw-pagehead tt-pagehead">{!phone && <h2>本机网关</h2>}<button type="button" onClick={onRoami}>Roami 模型设置</button></div>
    <nav className="gw-subtabs" aria-label="本机网关">{[['access', '接入与密钥'], ['directory', '模型目录']].map(([id, title]) => <button type="button" key={id} aria-pressed={tab === id} onClick={() => changeTab(id)}>{title}</button>)}</nav>
    {!panel && notice && <p className="gw-inline-notice" role="status">{notice}</p>}
    <div className="gw-layout"><div className="gw-scroll">
      {tab === 'access' ? <div className="gw-access-layout"><div className="gw-access-main"><section className="gw-address"><h3>接入地址</h3><div className="gw-copy-field"><code>{endpoint}</code><button type="button" className="quiet iconbutton" aria-label="复制接入地址" onClick={() => copy(endpoint)}><CopyIcon size={18} /></button></div><p className="meta">演示地址，仅宿主可访问；不代表已验证连通。</p><button type="button" className="quiet" onClick={() => changeTab('directory')}>查看模型目录</button></section>
      <section className="gw-key-list"><div className="gw-section-head"><h3>调用 Key</h3><button type="button" className="primary" onClick={() => open({ kind: 'create' })}><PlusIcon />新建 Key</button><button type="button" onClick={() => open({ kind: 'fixed' })}>固定 Key</button></div><p className="meta">调用方凭据；上游服务的 Key 在模型源中管理。</p>
        {keys.map(row => <div className="gw-key-row" key={row.id}><div><strong>{row.name}</strong><small>末尾 {row.suffix} / {row.enabled ? '已启用' : '已停用'}{row.fixed ? ' / 固定' : ''}</small></div><div className="gw-key-menu"><button type="button" className="quiet iconbutton" aria-label={'管理 ' + row.name} aria-expanded={menu === row.id} onClick={() => setMenu(menu === row.id ? null : row.id)}><MoreIcon size={18} /></button>{menu === row.id && <div className="gw-actions">{!row.fixed && <button type="button" onClick={() => open({ kind: 'rename', id: row.id })}>重命名</button>}<button type="button" onClick={() => { if (row.enabled) setConfirmation({ kind: 'disable', id: row.id }); else onKeys(previous => previous.map(item => item.id === row.id ? { ...item, enabled: true } : item)); setMenu(null) }}>{row.enabled ? '停用' : '启用'}</button>{!row.fixed && <button type="button" onClick={() => { setConfirmation({ kind: 'rotate', id: row.id }); setMenu(null) }}>轮换</button>}<button type="button" className="danger" onClick={() => { setConfirmation({ kind: 'delete', id: row.id }); setMenu(null) }}>删除</button></div>}</div></div>)}
        <p className="meta">历史 Key 只有哈希，不能再次复制全文；需要时轮换。</p>
      </section></div>
      <section className="gw-example"><div className="gw-section-head"><h3>调用示例</h3>{phone && <button type="button" aria-expanded={sampleOpen} onClick={() => setSampleOpen(!sampleOpen)}>{sampleOpen ? '收起' : '展开'}</button>}</div>{(!phone || sampleOpen) && <><label className="field">调用模型<select aria-label="调用示例模型" value={sample?.id || ''} onChange={event => setSampleId(event.target.value)}>{available.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label><div className="row">{['curl', 'Python'].map(value => <button type="button" key={value} aria-pressed={language === value} onClick={() => setLanguage(value)}>{value}</button>)}<button type="button" onClick={() => copy(code)}>复制示例</button></div><pre><code>{code}</code></pre><p className="meta">只引用环境变量，不把明文 Key 写进示例。</p></>}</section></div>
      : <><nav className="gw-directory-tabs" aria-label="模型范围">{directoryTabs.map(([id, title]) => <button type="button" key={id} aria-pressed={directoryTab === id} onClick={() => { setDirectoryTab(id); close() }}>{title}</button>)}</nav>
        <div className="gw-filters"><label className="field">搜索模型<input value={filter.query} onChange={event => updateFilter({ query: event.target.value })} placeholder="名称、调用名称或上游 ID" /></label>{directoryTab !== 'pools' && <label className="field">来源<select value={filter.source} onChange={event => updateFilter({ source: event.target.value })}><option value="">全部来源</option><option value="openrouter">OpenRouter</option><option value="openrouter-backup">备用 OpenRouter（演示）</option><option value="unverified">来源待核对</option></select></label>}<label className="field">能力<select value={filter.cap} onChange={event => updateFilter({ cap: event.target.value })}><option value="">全部能力</option>{caps.map(([id, title]) => <option value={id} key={id}>{title}</option>)}</select></label></div>
        <p className="meta">已接入表示目录配置存在；“原生 / 适配”能力另行核对。仅上游目录项先在源内启用。</p>
        <div className="gw-model-grid">{rows.map(model => <article className="gw-model-card" key={model.id}><button type="button" className="gw-card-open" aria-label={'查看 ' + model.name} onClick={() => open({ kind: 'model', id: model.id })} /><div><h3>{model.name}</h3><p className="meta">{kindLabel[model.kind]} / {model.sourceName || (model.kind === 'aggregate' ? 'Roami' : '来源待核对')}</p></div><div className="gw-card-capabilities"><span className="tag">{capabilitySummary(model)}</span></div>{model.kind === 'aggregate' ? <p>{model.strategy === 'weight' ? '权重分配' : '智能策略'} / {model.members?.length || 0} 个成员</p> : <p>{model.context ? `${model.context.toLocaleString('zh-CN')} tokens` : '上下文未知'}</p>}<footer><span className="meta">{model.configured === false ? '仅上游目录' : '已接入 / 路径未验证'}</span><button type="button" onClick={() => model.configured === false ? open({ kind: 'source', id: model.id }) : copy(model.id)}>{model.configured === false ? '到源中启用' : '复制调用名称'}</button></footer></article>)}</div>
        {!rows.length && <div className="empty"><p>没有符合条件的模型。</p><button type="button" onClick={() => updateFilter({ query: '', source: '', cap: '' })}>清除筛选</button></div>}
      </>}
    </div>
    {panel && <Inspector title={panel.kind === 'model' ? '模型详情' : panel.kind === 'pool' ? '编辑聚合' : panel.kind === 'source' ? '源内启用模型' : panel.kind === 'issued' ? '保存新的演示 Key' : panel.kind === 'rename' ? '重命名 Key' : panel.kind === 'fixed' ? '固定 Key' : '新建 Key'} onClose={close}>
      {notice && <p className="gw-inline-notice" role="status">{notice}</p>}
      {['model', 'source'].includes(panel.kind) && selected ? <><div className="gw-panel-scroll"><h3>{selected.name}</h3><dl><dt>{selected.configured === false ? '尚未分配调用名称' : '调用名称'}</dt><dd><code>{selected.configured === false ? '先到源中启用' : selected.id}</code></dd><dt>类型</dt><dd>{kindLabel[selected.kind]}</dd><dt>上游 ID</dt><dd><code>{selected.upstream || '由成员确定'}</code></dd><dt>能力</dt><dd>{capabilitySummary(selected)} / 路径未验证</dd></dl>{selected.members && <><h3>策略与成员</h3><p>{selected.strategy === 'weight' ? '权重分配' : '智能策略'} / {selected.freeOnly ? '仅免费' : '沿用定价规则'}</p><ul className="gw-members">{selected.members.map(member => <li key={member.id}><span>{findModel(member.id, catalog).name}</span><span className="tag">权重 {member.weight}</span></li>)}</ul></>}{panel.kind === 'source' && <p>这是 {selected.sourceName} 的目录模型；启用后会出现在同一份选模列表和调用示例中。</p>}</div><footer className="gw-panel-footer">{selected.configured === false ? <button type="button" className="primary" onClick={() => { onCatalog(previous => previous.map(model => model.id === selected.id ? { ...model, configured: true } : model)); setNotice('已在演示源中启用，可回 Roami 选择。'); close() }}>在演示中启用</button> : <><button type="button" onClick={() => showExample(selected.id)}>调用示例</button>{selected.kind === 'aggregate' && <button type="button" className="primary" onClick={() => { setPoolDraft(structuredClone(selected)); open({ kind: 'pool', id: selected.id }) }}>编辑聚合</button>}</>}</footer></>
      : panel.kind === 'pool' && poolDraft ? <form className="gw-panel-form" onSubmit={event => { event.preventDefault(); if (!poolDraft.members?.length) { setError('至少选择一个成员。'); return } onCatalog(previous => previous.map(model => model.id === poolDraft.id ? poolDraft : model)); close(); setNotice('聚合已更新，Roami 和任务选择同步使用。') }}><div className="gw-panel-scroll"><label className="field">名称<input value={poolDraft.name} onChange={event => setPoolDraft({ ...poolDraft, name: event.target.value })} required /></label><label className="field">策略<select value={poolDraft.strategy} onChange={event => setPoolDraft({ ...poolDraft, strategy: event.target.value as Model['strategy'] })}><option value="smart">智能策略</option><option value="weight">权重分配</option></select></label><label className="check"><input type="checkbox" checked={poolDraft.freeOnly} onChange={event => setPoolDraft({ ...poolDraft, freeOnly: event.target.checked })} />仅免费路径</label><h3>成员</h3>{available.filter(model => model.kind !== 'aggregate').map(model => { const member = poolDraft.members?.find(item => item.id === model.id); return <div className="gw-member-edit" key={model.id}><label className="check"><input type="checkbox" checked={!!member} onChange={() => setPoolDraft({ ...poolDraft, members: member ? poolDraft.members?.filter(item => item.id !== model.id) : [...(poolDraft.members || []), { id: model.id, weight: 1 }] })} />{model.name}</label>{member && poolDraft.strategy === 'weight' && <input type="number" min="1" max="1000" aria-label={model.name + ' 权重'} value={member.weight} onChange={event => setPoolDraft({ ...poolDraft, members: poolDraft.members?.map(item => item.id === model.id ? { ...item, weight: Math.max(1, Number(event.target.value)) } : item) })} />}</div> })}{error && <p className="danger" role="alert">{error}</p>}</div><footer className="gw-panel-footer"><button type="button" onClick={close}>取消</button><button type="submit" className="primary" onMouseDown={event => event.preventDefault()}>保存聚合</button></footer></form>
      : panel.kind === 'issued' ? <><div className="gw-panel-scroll"><p>这是演示凭据，只在本次生成后显示；关闭后不再保留全文。</p><textarea readOnly value={issued} aria-label="新生成的演示 Key" /><button type="button" onClick={() => copy(issued)}>复制新的 Key</button></div><footer className="gw-panel-footer"><button type="button" className="primary" onClick={close}>已保存</button></footer></>
      : <form className="gw-panel-form" onSubmit={saveKey}><div className="gw-panel-scroll"><label className="field">{panel.kind === 'fixed' ? '固定演示值' : '名称'}<input autoComplete="off" type={panel.kind === 'fixed' ? 'password' : 'text'} value={panel.kind === 'fixed' ? fixedDraft : panel.kind === 'rename' ? renameDraft : nameDraft} onChange={event => { if (panel.kind === 'fixed') setFixedDraft(event.target.value); else if (panel.kind === 'rename') setRenameDraft(event.target.value); else setNameDraft(event.target.value); setError('') }} /></label>{panel.kind === 'fixed' && <p className="meta">只使用演示值。替换后旧值立即失效，固定 Key 仍是独立单例配置。</p>}{error && <p className="danger" role="alert">{error}</p>}</div><footer className="gw-panel-footer"><button type="button" onClick={close}>取消</button><button type="submit" className="primary" onMouseDown={event => event.preventDefault()}>{panel.kind === 'create' ? '生成演示 Key' : '保存'}</button></footer></form>}
    </Inspector>}
    </div>
    {confirmation && <dialog ref={confirm} className="gw-confirm" onCancel={() => setConfirmation(null)}><h2>{confirmation.kind === 'replace' ? '替换固定 Key' : confirmation.kind === 'delete' ? '删除 Key' : confirmation.kind === 'rotate' ? '轮换 Key' : '停用 Key'}</h2><p>继续后，使用旧 Key 的调用方需要更新配置。</p><div className="row"><button type="button" onClick={() => setConfirmation(null)}>取消</button><button type="button" className="primary" onClick={confirmAction}>确认</button></div></dialog>}
  </div>
}
