import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useLayout } from '../../../frontend/src/layout'
import { AgentLogo, ChevronDown, ChevronLeft, ChevronRight, FileTextIcon, FolderIcon, MoonIcon, PanelRightIcon, SunIcon } from '../../../frontend/src/icons'

type Resource = 'chat' | 'plan' | 'checks'
type Group = 'sea' | 'login'
const groups: Group[] = ['sea', 'login']
const names = { sea: '海空双模式', login: '登录流程' }
const files: Record<string, string> = { plan: '交互方案.md', checks: '验收清单.md' }
const initialDraft = '# 海空双模式\n\n## 顶部标签组\n\n对话与文件收在同一个导航组里。\n\n点击“对话”，随时回到这段会话。\n文件标签继续保留，不必关闭文件。\n\n## 交互规则\n\n1. 组名：继续上次位置。\n2. 对话：直接返回会话。\n3. 文件名：直接打开文件。\n4. 展开箭头：只收起或展开标签。\n'

function App() {
  const layout = useLayout()
  const [group, setGroup] = useState<Group>('sea')
  const [resource, setResource] = useState<Resource>('plan')
  const [last, setLast] = useState<Record<Group, Resource>>({ sea: 'plan', login: 'chat' })
  const [folded, setFolded] = useState<Record<Group, boolean>>({ sea: false, login: true })
  const [page, setPage] = useState('content')
  const [light, setLight] = useState(false)
  const [inspector, setInspector] = useState(false)
  const [draft, setDraft] = useState(initialDraft)
  const [message, setMessage] = useState<Record<Group, string>>({ sea: '', login: '' })
  const [notice, setNotice] = useState('设计演示：在顶部组内切换对话和文件。')
  useEffect(() => { document.documentElement.dataset.theme = light ? 'light' : 'dark' }, [light])
  useEffect(() => {
    document.querySelector('.group-strip [aria-current="page"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [group, resource, folded, layout.phone, page])
  useEffect(() => {
    if (!location.hash) history.replaceState(null, '', '#group=sea&view=plan&page=content')
    const restore = () => {
      const p = new URLSearchParams(location.hash.slice(1))
      const g: Group = p.get('group') === 'login' ? 'login' : 'sea'
      const raw = p.get('view')
      const r: Resource = g === 'sea' && (raw === 'plan' || raw === 'checks') ? raw : 'chat'
      setGroup(g); setResource(r)
      setLast(old => ({ ...old, [g]: r }))
      setPage(p.get('page') === 'groups' ? 'groups' : 'content')
    }
    restore()
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])
  const navigate = (g: Group, r: Resource, p = 'content') => {
    setGroup(g); setResource(r); setPage(p)
    setLast(old => ({ ...old, [g]: r }))
    history.pushState(null, '', '#'+new URLSearchParams({ group: g, view: r, page: p }))
    setNotice(r === 'chat' ? '已返回对话，文件和草稿仍然保留。' : `正在查看 ${files[r]}，点组内“对话”可返回会话。`)
  }
  const resume = (g: Group) => {
    setFolded(old => ({ ...old, [g]: false }))
    navigate(g, last[g])
  }
  const tab = (g: Group, r: Resource) => <button type="button" key={r}
    className={`resource-tab ${group === g && resource === r ? 'selected' : ''}`}
    aria-current={group === g && resource === r ? 'page' : undefined}
    aria-label={r === 'chat' ? `打开${names[g]}的对话` : `打开${files[r]}`}
    onClick={() => navigate(g, r)}>
    {r === 'chat' ? <AgentLogo kind="claude" size={16} /> : <FileTextIcon size={16} />}
    <span>{r === 'chat' ? '对话' : files[r]}</span>
  </button>
  const topGroup = (g: Group) => <section role="group" aria-label={`${names[g]}标签组`} key={g}
    className={`tab-group ${group === g ? 'current-group' : ''} ${folded[g] ? 'folded' : ''}`}>
    {!layout.phone && <div className="group-head">
      <button type="button" className="group-name" aria-label={`继续${names[g]}`} onClick={() => resume(g)}>
        <FolderIcon size={16}/><span>{names[g]}</span>{folded[g] && <small>上次：{last[g] === 'chat' ? '对话' : files[last[g]]}</small>}
      </button>
      <button type="button" className="icon-button disclosure" aria-label={`${folded[g] ? '展开' : '收起'}${names[g]}标签组`} aria-expanded={!folded[g]}
        onClick={() => setFolded(old => ({ ...old, [g]: !old[g] }))}>
        {folded[g] ? <ChevronRight size={13}/> : <ChevronDown size={13}/>}
      </button>
    </div>}
    {(layout.phone || !folded[g]) && <div className="group-tabs">{tab(g, 'chat')}{g === 'sea' && [tab(g, 'plan'), tab(g, 'checks')]}</div>}
  </section>
  return <div className="prototype">
    <div className="design-bar"><strong>顶部标签组设计稿</strong><span>会话与文件收在同一组</span>
      <button type="button" className="icon-button" aria-label={light ? '切换深色' : '切换浅色'} onClick={() => setLight(!light)}>{light ? <MoonIcon size={18}/> : <SunIcon size={18}/>}</button>
    </div>
    <main className="main">
      {layout.phone ? <header className="mobile-bar"><button type="button" className="icon-button" aria-label={page === 'groups' ? '返回当前内容' : resource !== 'chat' ? '返回来源对话' : '选择工作区'} onClick={() => {
        if (page === 'groups') navigate(group, resource)
        else if (resource !== 'chat') navigate(group, 'chat')
        else navigate(group, resource, 'groups')
      }}><ChevronLeft size={20}/></button><div className="mobile-heading"><b>{page === 'groups' ? '工作区' : names[group]}</b><small>ai-app-factory</small></div>{page !== 'groups' && <button type="button" className="icon-button" aria-label="选择工作区" onClick={() => navigate(group, resource, 'groups')}><ChevronDown size={18}/></button>}</header>
      : <header className="workspace-head"><div className="project-identity"><b>Roami</b><ChevronRight size={14}/><span>ai-app-factory</span></div><button type="button" className="icon-button" aria-label={inspector ? '收起文件信息' : '展开文件信息'} aria-pressed={inspector} onClick={() => setInspector(!inspector)}><PanelRightIcon size={18}/></button></header>}
      {layout.phone && page === 'groups' ? <div className="group-picker" aria-label="工作区列表">{groups.map(g => <button type="button" className="picker-row" key={g} onClick={() => resume(g)}><FolderIcon size={20}/><span><b>{names[g]}</b><small>继续：{last[g] === 'chat' ? '对话' : files[last[g]]}</small></span><ChevronRight size={16}/></button>)}</div> : <>
        <nav className="group-strip" aria-label="工作区标签组">{(layout.phone ? [group] : groups).map(topGroup)}</nav>
        <div className="content-panes">
          <div className="primary-pane">
            {resource === 'chat' ? <>
              <div className="conversation" aria-label="会话内容"><div className="conversation-inner"><div className="message-meta">你</div><p>把对话和正在看的文件放在一起，方便来回切换。</p><div className="message-meta agent"><AgentLogo kind="claude" size={18}/> Claude</div><p>同一工作区的对话和文件会放在顶部同一组里。点击“对话”就回到这里，点击文件名就继续看文件。</p><div className="deliverables">{group === 'sea' ? [tab('sea', 'plan'), tab('sea', 'checks')] : <p>这个工作区还没有打开文件。</p>}</div><div className="message-meta">你</div><p>左边栏不需要再列一次，顶部能直接回来就好。</p><div className="message-meta agent"><AgentLogo kind="claude" size={18}/> Claude</div><p>顶部组内的“对话”一直在第一位，文件和输入草稿会继续保留。其他工作区收起时只占一个组名的位置。</p></div></div>
              <div className="composer"><label htmlFor="chat-draft">继续讨论</label><textarea id="chat-draft" value={message[group]} placeholder="输入消息（演示草稿）" onChange={e => { const value = e.target.value; setMessage(old => ({ ...old, [group]: value })) }}/><small>设计演示，不会发送消息</small></div>
            </> : <>
              {!layout.phone && <div className="file-title"><button type="button" className="icon-button" aria-label="返回来源对话" onClick={() => navigate('sea', 'chat')}><ChevronLeft size={18}/></button><strong>{files[resource]}</strong><span>docs / 海空双模式</span></div>}
              {resource === 'plan' ? <div className="editor"><label className="sr-only" htmlFor="file-draft">交互方案演示草稿</label><textarea id="file-draft" spellCheck={false} value={draft} onChange={e => setDraft(e.target.value)}/></div> : <article className="checks"><h1>验收清单</h1><p>从顶部组内回到对话，不需要关闭文件。</p><ul><li>对话标签固定在组内第一位。</li><li>文件标签紧跟所属会话。</li><li>多个组共享一条顶部导航。</li><li>收起组只收起标签，不切换内容。</li><li>切换对话和文件，草稿保持。</li></ul><p>这些是设计目标，尚未落地到产品。</p></article>}
            </>}
          </div>
          {!layout.phone && inspector && <aside className="inspector"><h2>{resource === 'chat' ? '会话信息' : '文件信息'}</h2><dl><dt>所属工作区</dt><dd>{names[group]}</dd><dt>当前内容</dt><dd>{resource === 'chat' ? '对话' : files[resource]}</dd><dt>路径</dt><dd>{resource === 'chat' ? 'ai-app-factory' : `docs/${files[resource]}`}</dd></dl><p>演示数据</p></aside>}
        </div>
      </>}
    </main>
    <div className="design-status" role="status">{notice}</div>
  </div>
}
createRoot(document.getElementById('root')!).render(<App/> )
