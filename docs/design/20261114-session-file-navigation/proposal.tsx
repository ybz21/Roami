import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useLayout } from '../../../frontend/src/layout'
import { AgentLogo, ChevronDown, ChevronLeft, ChevronRight, FileTextIcon, FolderIcon, HomeIcon, MoonIcon, PanelRightIcon, SunIcon } from '../../../frontend/src/icons'

type Resource = 'chat' | 'plan' | 'checks'
type Group = 'sea' | 'login'
const names = { sea: '海空双模式', login: '登录流程' }
const files: Record<string, string> = { plan: '交互方案.md', checks: '验收清单.md' }
const initialDraft = '# 海空双模式\n\n## 交互方案\n\n对话与文件在同一个工作区内并列。\n\n点击具体资源，总能到达明确的位置。\n\n## 导航规则\n\n1. 工作区名称：继续上次。\n2. 对话入口：回到指定会话。\n3. 文件入口：打开指定文件。\n4. 文件标题返回：回到来源对话。\n'

function App() {
  const layout = useLayout()
  const [group, setGroup] = useState<Group>('sea')
  const [resource, setResource] = useState<Resource>('plan')
  const [last, setLast] = useState<Record<Group, Resource>>({ sea: 'plan', login: 'chat' })
  const [folded, setFolded] = useState<Record<Group, boolean>>({ sea: false, login: true })
  const [page, setPage] = useState('resources')
  const [light, setLight] = useState(false)
  const [inspector, setInspector] = useState(true)
  const [draft, setDraft] = useState(initialDraft)
  const [message, setMessage] = useState('')
  const [notice, setNotice] = useState('演示：打开“对话”可直接返回，文件会保留。')
  useEffect(() => { document.documentElement.dataset.theme = light ? 'light' : 'dark' }, [light])
  useEffect(() => {
    if (!location.hash) history.replaceState(null, '', '#group=sea&view=plan&page=resources')
    const restore = () => {
      const p = new URLSearchParams(location.hash.slice(1))
      const g = p.get('group') === 'login' ? 'login' : 'sea'
      const r = p.get('view')
      setGroup(g)
      setResource(r === 'plan' || r === 'checks' ? r : 'chat')
      setLast(old => ({ ...old, [g]: r === 'plan' || r === 'checks' ? r : 'chat' }))
      setPage(p.get('page') || 'resources')
    }
    restore()
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])
  const navigate = (g: Group, r: Resource, p = 'content') => {
    setGroup(g); setResource(r); setPage(p)
    setLast(old => ({ ...old, [g]: r }))
    history.pushState(null, '', '#'+new URLSearchParams({ group: g, view: r, page: p }))
    setNotice(r === 'chat' ? '已返回对话，文件和草稿仍然保留。' : `正在查看 ${files[r]}，标题左侧可返回对话。`)
  }
  const resume = (g: Group) => navigate(g, last[g])
  const child = (g: Group, r: Resource) => <button type="button" key={r}
    className={`resource-row ${group === g && resource === r ? 'selected' : ''}`}
    aria-current={group === g && resource === r ? 'page' : undefined}
    aria-label={r === 'chat' ? `打开${names[g]}的对话` : `打开${files[r]}`}
    onClick={() => navigate(g, r)}>
    {r === 'chat' ? <AgentLogo kind="claude" size={18} /> : <FileTextIcon size={18} />}
    <span>{r === 'chat' ? '对话' : files[r]}</span>
    {r === 'chat' && <small>空闲</small>}
  </button>
  const groupRows = (g: Group) => <section className="workspace-group" key={g}>
    <div className={`group-row ${group === g ? 'ancestor' : ''}`}>
      <button type="button" className="icon-button disclosure" aria-label={`${folded[g] ? '展开' : '收起'}${names[g]}`} aria-expanded={!folded[g]}
        onClick={() => setFolded(old => ({ ...old, [g]: !old[g] }))}>
        {folded[g] ? <ChevronRight /> : <ChevronDown />}
      </button>
      <button type="button" className="group-name" onClick={() => resume(g)}>
        <FolderIcon size={18} /><span><b>{names[g]}</b>{folded[g] && <small>上次：{last[g] === 'chat' ? '对话' : files[last[g]]}</small>}</span>
      </button>
    </div>
    {!folded[g] && <div className="children" aria-label={`${names[g]}内的资源`}>{child(g, 'chat')}{g === 'sea' && [child(g, 'plan'), child(g, 'checks')]}</div>}
  </section>
  const mobileTitle = page === 'projects' ? '项目' : page === 'resources' ? names[group] : resource === 'chat' ? names[group] : files[resource]
  return <div className="prototype">
    <div className="design-bar"><strong>导航设计稿</strong><span>工作区内，对话与文件各自直达</span>
      <button type="button" className="quiet" onClick={() => { const g = group === 'sea' ? 'login' : 'sea'; navigate(g, last[g], layout.phone ? 'resources' : 'content') }}>切换工作区</button>
      <button type="button" className="icon-button" aria-label={light ? '切换深色' : '切换浅色'} onClick={() => setLight(!light)}>{light ? <MoonIcon size={18} /> : <SunIcon size={18} />}</button>
    </div>
    <div className="app-shell">
      {!layout.phone && <aside className="sidebar"><div className="brand">Roami <span>项目</span></div><div className="project-name">ai-app-factory</div>{groupRows('sea')}{groupRows('login')}</aside>}
      <main className="main">
        {layout.phone && <header className="mobile-bar"><button type="button" className="icon-button" aria-label={page === 'content' && resource !== 'chat' ? '返回来源对话' : '返回上一级'} onClick={() => {
          if (page === 'content' && resource !== 'chat') navigate(group, 'chat')
          else if (page === 'content') navigate(group, resource, 'resources')
          else setPage(page === 'resources' ? 'projects' : 'resources')
        }}><ChevronLeft size={20} /></button><div><b>{mobileTitle}</b>{page === 'content' && <small>{resource === 'chat' ? 'ai-app-factory' : names[group]}</small>}</div></header>}
        {layout.phone && page !== 'content' ? <div className="mobile-resources">
          {page === 'projects' ? <><h2>ai-app-factory</h2>{(['sea', 'login'] as Group[]).map(g => <button type="button" className="resource-row" key={g} onClick={() => { setGroup(g); setPage('resources') }}><FolderIcon size={20}/><span>{names[g]}</span><ChevronRight/></button>)}</> : <><div className="section-label">对话与打开的文件</div>{child(group, 'chat')}{group === 'sea' && [child(group, 'plan'), child(group, 'checks')]}<button type="button" className="resume quiet" onClick={() => resume(group)}>继续上次：{last[group] === 'chat' ? '对话' : files[last[group]]}</button></>}
        </div> : <>
          {!layout.phone && <header className="workspace-head"><div><FolderIcon size={18}/><strong>{names[group]}</strong><span>工作区</span></div><button type="button" className="icon-button" aria-label={inspector ? '收起文件信息' : '展开文件信息'} aria-pressed={inspector} onClick={() => setInspector(!inspector)}><PanelRightIcon size={18}/></button></header>}
          <nav className="tabs" aria-label="已打开的标签"><button type="button" aria-current={resource === 'chat' ? 'page' : undefined} className={resource === 'chat' ? 'active' : ''} onClick={() => navigate(group, 'chat')}><AgentLogo kind="claude" size={16}/>对话</button>{(['plan', 'checks'] as Resource[]).map(r => <button type="button" key={r} className={resource === r ? 'active' : ''} aria-current={resource === r ? 'page' : undefined} onClick={() => navigate('sea', r)}><FileTextIcon size={16}/>{files[r]}</button>)}</nav>
          <div className="content-panes">
            <div className="primary-pane">
              {resource === 'chat' ? <>
                <div className="conversation" aria-label="会话内容"><div className="conversation-inner"><div className="message-meta">你</div><p>把对话和正在看的文件放在一起，方便来回切换。</p><div className="message-meta agent"><AgentLogo kind="claude" size={18}/> Claude</div><p>我整理了两个文件。你可以先看交互方案，再回到这里继续讨论。</p><div className="deliverables">{group === 'sea' ? [child('sea', 'plan'), child('sea', 'checks')] : <p>这个工作区还没有打开文件。</p>}</div><div className="message-meta">你</div><p>看完文件后，我要能直接回到这段对话。</p><div className="message-meta agent"><AgentLogo kind="claude" size={18}/> Claude</div><p>可以。组内的“对话”入口一直保留；文件标题左侧也有返回对话的箭头。文件和输入内容都会保留。</p></div></div>
                <div className="composer"><label htmlFor="chat-draft">继续讨论</label><textarea id="chat-draft" value={message} placeholder="输入消息（演示草稿）" onChange={e => setMessage(e.target.value)}/><small>设计演示，不会发送消息</small></div>
              </> : <>
                {!layout.phone && <div className="file-title"><button type="button" className="icon-button" aria-label="返回来源对话" onClick={() => navigate('sea', 'chat')}><ChevronLeft size={18}/></button><strong>{files[resource]}</strong><span>docs / 海空双模式</span></div>}
                {resource === 'plan' ? <div className="editor"><label className="sr-only" htmlFor="file-draft">交互方案演示草稿</label><textarea id="file-draft" spellCheck={false} value={draft} onChange={e => setDraft(e.target.value)}/></div> : <article className="checks"><h1>验收清单</h1><p>回到对话时，不需要关闭文件。</p><ul><li>会话入口直接回到对话。</li><li>文件入口直接打开文件。</li><li>切走再回来，工作区恢复上次位置。</li><li>折叠不改变当前内容。</li><li>草稿和滚动位置保持。</li></ul><p>这些是设计目标，尚未落地到产品。</p></article>}
              </>}
            </div>
            {!layout.phone && inspector && <aside className="inspector"><h2>工作区内容</h2><div className="section-label">会话</div>{child(group, 'chat')}<div className="section-label">已打开文件</div>{group === 'sea' ? [child('sea', 'plan'), child('sea', 'checks')] : <p>尚未打开文件</p>}<div className="inspector-note"><b>当前落点</b><p>{resource === 'chat' ? '对话' : files[resource]}</p><small>对话和文件共用工作区，分别保留位置。</small></div></aside>}
          </div>
        </>}
        {layout.phone && page === 'projects' && <nav className="bottom-nav" aria-label="主导航"><span><HomeIcon size={20}/>首页</span><strong><FolderIcon size={20}/>项目</strong><span><FileTextIcon size={20}/>工具</span><span><PanelRightIcon size={20}/>设置</span></nav>}
      </main>
    </div>
    <div className="design-status" role="status">{notice}</div>
  </div>
}

createRoot(document.getElementById('root')!).render(<App/> )
