import { useEffect, useRef, useState } from 'react'
import { App as AntApp } from 'antd'
import { api } from '../../api'
import { closeSession, sessionActionError } from './session-actions'
import { nativeSessionId } from './session-record'
import { useI18n } from '../../i18n'
import { CloseWorktreeModal } from './CloseWorktreeModal'

export function useSessionCloser(closeTerm: (n: string) => void, afterClose?: () => void) {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [closing, setClosing] = useState<{ name: string; st: any } | null>(null)
  const [checkingName, setCheckingName] = useState<string | null>(null)
  const checking = useRef<AbortController | null>(null)
  const cancelCheck = () => {
    const request = checking.current
    checking.current = null
    setCheckingName(null)
    request?.abort()
  }
  useEffect(() => () => { checking.current?.abort(); checking.current = null }, [])
  const done = (n: string) => { message.success(t('session.lifecycle.closeAccepted')); closeTerm(n); afterClose?.() }
  const kill = async (n: string) => {
    try { await closeSession(n); done(n) } catch (e: any) { message.error(sessionActionError(e, t)) }
  }
  const beginClose = async (n: string) => {
    if (checking.current) return
    setClosing(null)
    let st: any = null
    if (!nativeSessionId(n)) {
      const request = new AbortController()
      checking.current = request
      setCheckingName(n)
      try {
        st = (await api('GET', `/sessions/${encodeURIComponent(n)}/worktree-status`, undefined, { signal: request.signal }))?.data
        if (checking.current !== request) return
      } catch {
        if (checking.current === request) message.error(t('session.closeCheckFailed'))
        return
      } finally {
        if (checking.current === request) {
          checking.current = null
          setCheckingName(null)
        }
      }
    }
    setClosing({ name: n, st })
  }
  const node = <CloseWorktreeModal info={checkingName ? { name: checkingName, st: null } : closing}
    checking={checkingName !== null} sessionConfirmation onClose={() => { cancelCheck(); setClosing(null) }}
    onDone={(name) => { closeTerm(name); afterClose?.() }} />
  return { beginClose, kill, node }
}
