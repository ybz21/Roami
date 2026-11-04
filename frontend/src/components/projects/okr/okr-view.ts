import { useEffect, useState } from 'react'
import { useCurrentNodeId } from '../../cluster/node-url'

export function useOkrView(projectId: string) {
  const node = useCurrentNodeId()
  const key = 'roam.okr.view:' + JSON.stringify([node, projectId])
  const [view, setView] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || '{}')
      return {
        mainPanel: ['board', 'activities', 'files'].includes(saved.mainPanel) ? saved.mainPanel as string : 'board',
        panel: ['overview', 'data', 'review'].includes(saved.panel) ? saved.panel as string : 'overview',
      }
    } catch { return { mainPanel: 'board', panel: 'overview' } }
  })
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(view)) } catch { /* 当前页面仍可切换 */ }
  }, [key, view])
  return {
    ...view,
    setMainPanel: (mainPanel: string) => setView(current => ({ ...current, mainPanel })),
    setPanel: (panel: string) => setView(current => ({ ...current, panel })),
  }
}
