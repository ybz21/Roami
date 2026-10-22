import { useEffect, useRef, useState } from 'react'
import { Button, Modal } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import './repository-setup.css'

type RepositoryState = { repo: boolean; hasCommits: boolean; root?: string }

export function useRepositorySetup(dir: string, hint?: boolean) {
  const [snapshot, setSnapshot] = useState<{ dir: string; data?: RepositoryState; error?: boolean }>()
  const [revision, setRevision] = useState(0)
  const [initializing, setInitializing] = useState(false)
  const pending = useRef(false)
  const currentDir = useRef(dir)
  currentDir.current = dir
  useEffect(() => {
    if (!dir) return
    const controller = new AbortController()
    setSnapshot(undefined)
    api('GET', `/git/is-repo?path=${encodeURIComponent(dir)}`, undefined, { signal: controller.signal })
      .then((r) => {
        if (typeof r.data?.repo !== 'boolean' || typeof r.data?.hasCommits !== 'boolean') throw new Error('GIT_PROBE_FAILED')
        if (!controller.signal.aborted) setSnapshot({ dir, data: r.data })
      })
      .catch(() => { if (!controller.signal.aborted) setSnapshot({ dir, error: true }) })
    return () => controller.abort()
  }, [dir, hint, revision])
  const data = snapshot?.dir === dir ? snapshot.data : undefined
  const failed = snapshot?.dir === dir && !!snapshot.error
  const checking = !!dir && !data && !failed
  const initialize = async () => {
    if (pending.current) return
    pending.current = true
    setInitializing(true)
    try {
      const r = await api('POST', '/git/initialize', { dir })
      if (currentDir.current === dir) setSnapshot({ dir, data: r.data })
    } finally {
      pending.current = false
      setInitializing(false)
    }
  }
  return {
    checking, failed, initializing,
    ready: !!data?.repo && data.hasCommits === true,
    repo: !!data?.repo,
    blocked: checking || failed || initializing,
    initialize,
    retry: () => setRevision((v) => v + 1),
  }
}

export function RepositorySetup({ setup }: { setup: ReturnType<typeof useRepositorySetup> }) {
  const { t } = useI18n()
  const [confirming, setConfirming] = useState(false)
  const [failure, setFailure] = useState('')
  if (setup.ready) return null
  const initialize = async () => {
    try {
      setFailure('')
      await setup.initialize()
      setConfirming(false)
    } catch (error) { setFailure(error instanceof Error ? error.message : String(error)) }
  }
  return <>
    <div className="tt-repository-setup" role="status">
      <span>{t(setup.checking ? 'session.gitSetup.checking' : setup.failed ? 'session.gitSetup.checkFailed' : setup.repo ? 'session.gitSetup.empty' : 'session.gitSetup.plain')}</span>
      {!setup.checking && (setup.failed
        ? <Button size="small" onClick={setup.retry}>{t('session.gitSetup.retry')}</Button>
        : <Button size="small" loading={setup.initializing} onClick={() => { setFailure(''); setConfirming(true) }}>{t(setup.repo ? 'session.gitSetup.commitAction' : 'session.gitSetup.initAction')}</Button>)}
    </div>
    <Modal className="tt-repository-confirm" open={confirming} title={t(setup.repo ? 'session.gitSetup.commitTitle' : 'session.gitSetup.initTitle')}
      okText={t('session.gitSetup.confirmAction')} cancelText={t('common.cancel')}
      confirmLoading={setup.initializing} cancelButtonProps={{ disabled: setup.initializing }}
      closable={!setup.initializing} maskClosable={!setup.initializing} onCancel={() => setConfirming(false)} onOk={initialize}>
      <p>{t('session.gitSetup.confirm')}</p>
      {failure && <div role="alert">
        <p>{t('session.gitSetup.failed')}</p>
        <details><summary>{t('session.gitSetup.errorDetails')}</summary><pre className="tt-repository-error">{failure}</pre></details>
      </div>}
    </Modal>
  </>
}
