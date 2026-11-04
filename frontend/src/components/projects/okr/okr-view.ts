import { useEffect, useState } from 'react'
import { useCurrentNodeId } from '../../cluster/node-url'

export function useOkrView(projectId: string) {
  const node = useCurrentNodeId()
  const key = 'roam.okr.view:' + JSON.stringify([node, projectId])
  const [mainPanel, setMainPanel] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || '{}')
      if (['okr', 'data', 'activities', 'memory', 'files'].includes(saved.mainPanel)) return saved.mainPanel as string
      return saved.mainPanel === 'board' && saved.panel === 'data' ? 'data' : 'okr'
    } catch { return 'okr' }
  })
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify({ mainPanel })) } catch { /* 当前页面仍可切换 */ }
  }, [key, mainPanel])
  return { mainPanel, setMainPanel }
}
