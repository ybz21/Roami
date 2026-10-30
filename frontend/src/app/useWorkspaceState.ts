import { message } from 'antd'
import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react'
import { api } from '../api'
import { currentNodeId } from '../components/cluster/node-url'
import { loadTabs, forgetTabs } from '../components/terminal/term-tabs-store'
import { useI18n } from '../i18n'
import { getHashParams, readTermTokens, setHashParams } from '../route-hash'
import { pollWhileVisible } from '../visible-poll'
import { createWorkspaceState } from './workspace-state'
import type { SessionDirectory } from './useSessionDirectory'

export function useWorkspaceState(nodeId: string | null, directory: SessionDirectory) {
  const { t } = useI18n()
  const directoryRef = useRef(directory)
  directoryRef.current = directory
  const store = useMemo(() => createWorkspaceState(async (...args) => {
    if (currentNodeId() !== nodeId) throw new Error('WORKSPACE_NODE_CHANGED')
    const response = await api(...args)
    if (currentNodeId() !== nodeId) throw new Error('WORKSPACE_NODE_CHANGED')
    return response
  }, () => {
    const legacy = loadTabs(nodeId)
    const url = readTermTokens()
    const ids = directoryRef.current.sessIds
    const terms = (url.terms.length ? url.terms : legacy.terms).map(id => ids?.byName[id] || id).filter(id => !!ids?.byId[id])
    const selected = url.active || legacy.active
    return { ...legacy, terms, active: ids?.byName[selected] || selected }
  }, () => {
    forgetTabs(nodeId)
    const params = Object.fromEntries(getHashParams())
    delete params.terms; delete params.active
    setHashParams(params)
  }), [nodeId])
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot)
  useEffect(() => {
    if (!directory.sessListLoaded) return
    const poll = pollWhileVisible(signal => store.refresh(signal), 5000)
    return poll.stop
  }, [store, directory.sessListLoaded])
  useEffect(() => { if (snapshot.error) void message.error(t('workspace.syncFailed')) }, [snapshot.error, t])
  return { ...snapshot, update: store.update }
}
