import { App as AntApp, ConfigProvider } from 'antd'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { PageActivityProvider } from '../page-activity'

const ownScroll = new Set(['home', 'onboarding', 'capabilities', 'settings', 'browser', 'phone', 'files'])

export default function RetainedPage({ page, active, mobile, hasDock, children }: {
  page: string; active: boolean; mobile: boolean; hasDock: boolean; children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [popups] = useState(() => document.createElement('div'))
  useLayoutEffect(() => {
    document.body.appendChild(popups)
    return () => popups.remove()
  }, [popups])
  useLayoutEffect(() => {
    popups.style.display = active ? '' : 'none'
    if (ref.current) ref.current.inert = !active
  }, [active, popups])
  return <PageActivityProvider active={active}>
    <div ref={ref} data-page={page} aria-hidden={!active}
      className={`tt-page tt-page-${page}${mobile ? ' tt-page-mobile' : ''}${mobile && hasDock ? ' has-dock' : ''}`}
      style={{ display: active ? undefined : 'none', height: '100%', minHeight: 0, overflow: ownScroll.has(page) ? 'hidden' : 'auto' }}>
      <ConfigProvider getPopupContainer={() => popups}>
        <AntApp component={false} message={{ getContainer: () => popups }} notification={{ getContainer: () => popups }}>{children}</AntApp>
      </ConfigProvider>
    </div>
  </PageActivityProvider>
}
