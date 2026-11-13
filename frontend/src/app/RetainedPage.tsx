import { App as AntApp, ConfigProvider } from 'antd'
import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { PageActivityProvider, usePageActive } from '../page-activity'
import { PageViewStateProvider } from '../page-view-state'
import { usePageScroll } from '../page-scroll'

const ownScroll = new Set(['home', 'onboarding', 'capabilities', 'settings', 'browser', 'phone', 'files'])
const unloadHidden = new Set(['files', 'browser', 'phone'])

export default function RetainedPage({ page, active, mobile, hasDock, children }: {
  page: string; active: boolean; mobile: boolean; hasDock: boolean; children: ReactNode
}) {
  const [operations, setOperations] = useState(0)
  const retain = useCallback(() => {
    setOperations(count => count + 1)
    let released = false
    return () => { if (!released) { released = true; setOperations(count => count - 1) } }
  }, [])
  const [memory] = useState(() => new Map<string, unknown>())
  const [popups] = useState(() => document.createElement('div'))
  useLayoutEffect(() => {
    document.body.appendChild(popups)
    return () => popups.remove()
  }, [popups])
  useLayoutEffect(() => {
    popups.style.display = active ? '' : 'none'
  }, [active, popups])
  return <PageActivityProvider active={active}>
    <PageViewStateProvider memory={memory} retain={retain}>
      <PageBody page={page} active={active} mobile={mobile} hasDock={hasDock} popups={popups} retained={operations > 0}>{children}</PageBody>
    </PageViewStateProvider>
  </PageActivityProvider>
}

function PageBody({ page, active, mobile, hasDock, popups, retained, children }: {
  page: string; active: boolean; mobile: boolean; hasDock: boolean; popups: HTMLElement; retained: boolean; children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const scroll = usePageScroll(ref, usePageActive())
  useLayoutEffect(() => { if (ref.current) ref.current.inert = !active }, [active])
  return <div ref={ref} data-page={page} aria-hidden={!active} {...scroll}
      className={`tt-page tt-page-${page}${mobile ? ' tt-page-mobile' : ''}${mobile && hasDock ? ' has-dock' : ''}`}
      style={{ display: active ? undefined : 'none', height: '100%', minHeight: 0, overflow: ownScroll.has(page) ? 'hidden' : 'auto' }}>
      {(active || retained || !unloadHidden.has(page)) && <ConfigProvider getPopupContainer={() => popups}>
        <AntApp component={false} message={{ getContainer: () => popups }} notification={{ getContainer: () => popups }}>{children}</AntApp>
      </ConfigProvider>}
    </div>
}
