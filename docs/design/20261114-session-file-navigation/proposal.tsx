import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { useLayout } from '../../../frontend/src/layout'
import { AgentLogo, CheckIcon, ChevronDown, ChevronLeft, ChevronRight, FileTextIcon, MoonIcon, PanelRightIcon, SunIcon } from '../../../frontend/src/icons'

type Resource = 'chat' | 'plan' | 'checks'
type Group = 'sea' | 'login'
const groups: Group[] = ['sea', 'login']
const names = { sea: '海空双模式', login: '登录流程' }
const agents = { sea: 'claude', login: 'codex' } as const
const files: Record<string, string> = { plan: '交互方案.md', checks: '验收清单.md' }
const initialDraft = '# 海空双模式\n\n## 智能体入口与下拉菜单\n\n保留智能体 Logo 和会话名。\n\n点击 Logo 或名称，直接回到对话。\n点击旁边的下拉箭头，选择对话或文件。\n\n## 交互规则\n\n1. 会话入口始终回到对话。\n2. 下拉菜单展示该组已打开文件。\n3. 文件名打开指定文件。\n4. 关闭菜单不关闭文件。\n'

function App() {
  const layout = useLayout()
  const [group, setGroup] = useState<Group>('sea')
  const [resource, setResource] = useState<Resource>('plan')
  const [page, setPage] = useState('content')
  const [light, setLight] = useState(false)
  const [inspector, setInspector] = useState(false)
  const [draft, setDraft] = useState(initialDraft)
  const [message, setMessage] = useState<Record<Group, string>>({ sea: '', login: '' })
  const [openGroup, setOpenGroup] = useState<Group | null>(null)
  const [anchor, setAnchor] = useState({ left: 0, bottom: 0 })
  const menu = useRef<HTMLDivElement>(null)
  const triggers = useRef<Partial<Record<Group, HTMLButtonElement | null>>>({})
  const [notice, setNotice] = useState('设计演示：点击智能体入口回对话，箭头展开文件。')
  useEffect(() => { document.documentElement.dataset.theme = light ? 'light' : 'dark' }, [light])
  useEffect(() => {
    if (!location.hash) history.replaceState(null, '', '#group=sea&view=plan&page=content')
    const restore = () => {
      const p = new URLSearchParams(location.hash.slice(1))
      const g: Group = p.get('group') === 'login' ? 'login' : 'sea'
      const raw = p.get('view')
      const r: Resource = g === 'sea' && (raw === 'plan' || raw === 'checks') ? raw : 'chat'
      setGroup(g); setResource(r); setOpenGroup(null)
      setPage(p.get('page') === 'groups' ? 'groups' : 'content')
    }
    restore(); window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])
  useEffect(() => {
    if (!openGroup) return
    const selected = menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]') || menu.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"]')
    selected?.focus({ preventScroll: true })
    const outside = (event: PointerEvent) => {
      const target = event.target as Element
      if (!target.closest('.session-dropdown, .group-trigger')) setOpenGroup(null)
    }
    const reposition = (event: Event) => {
      if (menu.current?.contains(event.target as Node)) return
      setOpenGroup(null)
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  }, [openGroup])
  const navigate = (g: Group, r: Resource, p = 'content') => {
    setGroup(g); setResource(r); setPage(p); setOpenGroup(null)
    history.pushState(null, '', '#'+new URLSearchParams({ group: g, view: r, page: p }))
    setNotice(r === 'chat' ? '已返回对话，文件与草稿仍然保留。' : `正在查看 ${files[r]}，点击智能体入口可回对话。`)
  }
  const toggleMenu = (g: Group, element: HTMLButtonElement) => {
    const rect = element.parentElement!.getBoundingClientRect()
    setAnchor({ left: rect.left, bottom: rect.bottom })
    setOpenGroup(old => old === g ? null : g)
  }
  const select = (g: Group, r: Resource) => { navigate(g, r); triggers.current[g]?.focus({ preventScroll: true }) }
  const resourceButton = (r: Resource) => <button type="button" className="resource-link" key={r} onClick={() => navigate('sea', r)}><FileTextIcon size={16}/><span>{files[r]}</span></button>
  const groupEntry = (g: Group) => <div className={`agent-group ${group === g ? 'current-group' : ''}`} role="group" aria-label={`${names[g]}会话及文件`} key={g}>
    <button type="button" className={`session-entry ${group === g && resource === 'chat' ? 'selected' : ''}`} aria-label={`打开${names[g]}的对话`} aria-current={group === g && resource === 'chat' ? 'page' : undefined} onClick={() => navigate(g, 'chat')}><AgentLogo kind={agents[g]} size={18}/><span>{names[g]}</span></button>
    <button type="button" className="group-trigger icon-button" ref={element => { triggers.current[g] = element }} aria-label={`${names[g]}的对话和文件`} aria-haspopup="menu" aria-expanded={openGroup === g} aria-controls={openGroup === g ? 'resource-menu' : undefined} onClick={e => toggleMenu(g, e.currentTarget)} onKeyDown={e => { if (e.key === 'ArrowDown') { e.preventDefault(); toggleMenu(g, e.currentTarget) } }}><ChevronDown size={14}/></button>
  </div>
  const menuItem = (g: Group, r: Resource) => <button type="button" role="menuitemradio" aria-checked={group === g && resource === r} className="menu-item" key={r} onClick={() => select(g, r)}>
    {r === 'chat' ? <AgentLogo kind={agents[g]} size={18}/> : <FileTextIcon size={18}/>}
    <span>{r === 'chat' ? '对话' : files[r]}</span>{group === g && resource === r && <CheckIcon size={15}/>}
  </button>
  const dropdown = openGroup && createPortal(<div ref={menu} id="resource-menu" role="menu" aria-label={`${names[openGroup]}的对话和文件`} className="session-dropdown" style={{ '--anchor-left': `${anchor.left}px`, '--anchor-bottom': `${anchor.bottom}px` } as React.CSSProperties} onKeyDown={e => {
    const items = Array.from(menu.current!.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'))
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    if (e.key === 'Escape') { e.preventDefault(); const g = openGroup; setOpenGroup(null); triggers.current[g]?.focus() }
    else if (['ArrowDown','ArrowUp','Home','End'].includes(e.key)) {
      e.preventDefault()
      const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (index + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
      items[next]?.focus()
    } else if (e.key === 'Tab') { setOpenGroup(null); triggers.current[openGroup]?.focus() }
  }}>{menuItem(openGroup, 'chat')}{openGroup === 'sea' && <><div className="menu-section" role="presentation">已打开文件</div>{menuItem(openGroup, 'plan')}{menuItem(openGroup, 'checks')}</>}</div>, document.body)
  return <div className="prototype">
    <div className="design-bar"><strong>智能体下拉导航设计稿</strong><span>智能体 Logo 与名称直达对话，箭头选择文件</span><button type="button" className="icon-button" aria-label={light ? '切换深色' : '切换浅色'} onClick={() => setLight(!light)}>{light ? <MoonIcon size={18}/> : <SunIcon size={18}/>}</button></div>
    <main className="main">
      {layout.phone ? <header className="mobile-bar"><button type="button" className="icon-button" aria-label={page === 'groups' ? '返回当前内容' : resource !== 'chat' ? '返回来源对话' : '选择会话'} onClick={() => page === 'groups' ? navigate(group, resource) : resource !== 'chat' ? navigate(group, 'chat') : navigate(group, resource, 'groups')}><ChevronLeft size={20}/></button>{page === 'groups' ? <div className="mobile-heading"><b>会话</b><small>ai-app-factory</small></div> : groupEntry(group)}</header>
      : <header className="workspace-head"><div className="project-identity"><b>Roami</b><ChevronRight size={14}/><span>ai-app-factory</span></div><button type="button" className="icon-button" aria-label={inspector ? '收起文件信息' : '展开文件信息'} aria-pressed={inspector} onClick={() => setInspector(!inspector)}><PanelRightIcon size={18}/></button></header>}
      {layout.phone && page === 'groups' ? <div className="group-picker" aria-label="会话列表">{groups.map(g => <button type="button" className="picker-row" key={g} onClick={() => navigate(g, 'chat')}><AgentLogo kind={agents[g]} size={20}/><span><b>{names[g]}</b><small>{agents[g] === 'claude' ? 'Claude' : 'Codex'}</small></span><ChevronRight size={16}/></button>)}</div> : <>
        {!layout.phone && <nav className="group-strip" aria-label="会话与文件分组">{groups.map(groupEntry)}</nav>}
        <div className="content-panes"><div className="primary-pane">
          {resource === 'chat' ? <><div className="conversation" aria-label="会话内容"><div className="conversation-inner"><div className="message-meta">你</div><p>保留智能体的 Logo，再加一个下拉框来找文件。</p><div className="message-meta agent"><AgentLogo kind={agents[group]} size={18}/> {agents[group] === 'claude' ? 'Claude' : 'Codex'}</div><p>点击智能体 Logo 或名称会直接回到这段对话。旁边的箭头列出对话和已打开文件，选择文件后菜单收起。</p><div className="deliverables">{group === 'sea' ? [resourceButton('plan'),resourceButton('checks')] : <p>这个会话还没有打开文件。</p>}</div><div className="message-meta">你</div><p>这样看完文件就能直接回来，不用关闭文件。</p><div className="message-meta agent"><AgentLogo kind={agents[group]} size={18}/> {agents[group] === 'claude' ? 'Claude' : 'Codex'}</div><p>是的。文件标题会显示当前文件，菜单标出当前项；智能体入口的名称保持不变。</p></div></div><div className="composer"><label htmlFor="chat-draft">继续讨论</label><textarea id="chat-draft" value={message[group]} placeholder="输入消息（演示草稿）" onChange={e => { const value=e.target.value; setMessage(old=>({...old,[group]:value})) }}/><small>设计演示，不会发送消息</small></div></>
          : <><div className="file-title">{!layout.phone && <button type="button" className="icon-button" aria-label="返回来源对话" onClick={()=>navigate('sea','chat')}><ChevronLeft size={18}/></button>}<strong>{files[resource]}</strong><span>docs / 海空双模式</span></div>{resource === 'plan' ? <div className="editor"><label className="sr-only" htmlFor="file-draft">交互方案演示草稿</label><textarea id="file-draft" spellCheck={false} value={draft} onChange={e=>setDraft(e.target.value)}/></div> : <article className="checks"><h1>验收清单</h1><p>智能体入口始终回到对话。</p><ul><li>保留官方智能体 Logo。</li><li>点名称回到对话，点箭头打开菜单。</li><li>菜单先列对话，再列已打开文件。</li><li>当前资源同时有文字与选中标记。</li><li>选文件或关闭菜单，不丢草稿。</li></ul><p>这些是设计目标，尚未落地到产品。</p></article>}</>}
        </div>{!layout.phone && inspector && <aside className="inspector"><h2>{resource === 'chat' ? '会话信息' : '文件信息'}</h2><dl><dt>所属工作区</dt><dd>{names[group]}</dd><dt>当前内容</dt><dd>{resource === 'chat' ? '对话' : files[resource]}</dd><dt>路径</dt><dd>{resource === 'chat' ? 'ai-app-factory' : `docs/${files[resource]}`}</dd></dl><p>演示数据</p></aside>}</div>
      </>}
    </main><div className="design-status" role="status">{notice}</div>{dropdown}
  </div>
}
createRoot(document.getElementById('root')!).render(<App/> )
