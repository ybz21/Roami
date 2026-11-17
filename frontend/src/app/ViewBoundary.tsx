import { App as AntApp, ConfigProvider } from 'antd'
import { useCallback, useMemo, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { PageActivityProvider, usePageActive } from '../page-activity'
import { WorkspaceStateProvider, ViewStateProvider, useWorkspaceStateStore } from '../view-state'
import type { ViewStateScope } from '../workspace-state'
import { usePageScroll } from '../page-scroll'

export type ViewLifetime = 'unmount' | 'retain'
type Props = {
  page: string; active: boolean; mobile: boolean; hasDock: boolean; children: ReactNode
  scope?: ViewStateScope; lifetime?: ViewLifetime; scroll?: 'page' | 'content'
}

export default function ViewBoundary(props: Props) {
  return <WorkspaceStateProvider><PageScope {...props} /></WorkspaceStateProvider>
}
function PageScope({ page, active, mobile, hasDock, children, scope: provided, lifetime = 'unmount', scroll = 'page' }: Props) {
  const store = useWorkspaceStateStore()
  const scope = useMemo(() => provided || store.scope('page', page), [provided, store, page])
  const [operations, setOperations] = useState(0)
  const retain = useCallback(() => {
    setOperations(count => count + 1)
    let released = false
    return () => { if (!released) { released = true; setOperations(count => count - 1) } }
  }, [])
  const [popups] = useState(() => document.createElement('div'))
  useLayoutEffect(() => {
    document.body.appendChild(popups)
    return () => popups.remove()
  }, [popups])
  useLayoutEffect(() => {
    popups.style.display = active ? '' : 'none'
  }, [active, popups])
  return <PageActivityProvider active={active}>
    <ViewStateProvider scope={scope} retain={retain}>
      <PageBody page={page} active={active} mobile={mobile} hasDock={hasDock} popups={popups} retained={operations > 0 || lifetime === 'retain'} ownScroll={scroll === 'content'}>{children}</PageBody>
    </ViewStateProvider>
  </PageActivityProvider>
}

function PageBody({ page, active, mobile, hasDock, popups, retained, ownScroll, children }: {
  page: string; active: boolean; mobile: boolean; hasDock: boolean; popups: HTMLElement; retained: boolean; ownScroll: boolean; children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const scroll = usePageScroll(ref, usePageActive())
  useLayoutEffect(() => { if (ref.current) ref.current.inert = !active }, [active])
  return <div ref={ref} data-page={page} aria-hidden={!active} {...scroll}
      className={`tt-page tt-page-${page}${mobile ? ' tt-page-mobile' : ''}${mobile && hasDock ? ' has-dock' : ''}`}
      style={{ display: active ? undefined : 'none', height: '100%', minHeight: 0, overflow: ownScroll ? 'hidden' : 'auto' }}>
      {(active || retained) && <ConfigProvider getPopupContainer={() => popups}>
        <AntApp component={false} message={{ getContainer: () => popups }} notification={{ getContainer: () => popups }}>{children}</AntApp>
      </ConfigProvider>}
    </div>
}
