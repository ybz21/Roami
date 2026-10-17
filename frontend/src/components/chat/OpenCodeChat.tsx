import { memo, useMemo } from 'react'
import { ChatShell } from './ChatShell'
import { Typing } from './blocks'
import { ChatMessage, CODEX_ACCENT } from './Message'
import { useTranscript, pairToolResults } from './useTranscript'
import { buildTaskIndex } from './tasks'
import { toAgentStatus } from './status'
import { deriveFromMessages } from './status-derive'
import { useSessionLabel } from '../sessions/session-label'
import { useI18n } from '../../i18n'

export default memo(function OpenCodeChat({ name, file, onOpenFile, onOpenGit, active }: { name: string; file?: string; onOpenFile?: (path: string, line?: number) => void; onOpenGit?: () => void; active?: boolean }) {
  const { t } = useI18n()
  const label = useSessionLabel(name)
  const { msgs, err, status: raw, hasEarlier, loadEarlier, resolvedFile, serverPending } = useTranscript(name, file, 'opencode-transcript', active === false ? 6000 : 1500)
  const { results, view } = useMemo(() => pairToolResults(msgs), [msgs])
  const pending = serverPending === true
  const tasks = useMemo(() => buildTaskIndex(view, results), [view, results])
  const derived = useMemo(() => deriveFromMessages(view), [view])
  const status = useMemo(() => ({ ...toAgentStatus(raw, tasks), errors: derived.errors, elapsed: derived.elapsed }), [raw, tasks, derived])

  return <ChatShell
    emptyHint={resolvedFile !== undefined && msgs.length === 0 ? t('chat.noTranscriptYet') : undefined}
    name={name} accent={CODEX_ACCENT} error={err} onOpenFile={onOpenFile} tasks={tasks} status={status} onOpenGit={onOpenGit} lastErrorId={derived.lastErrorId}
    placeholder={t('chat.sendTo', { name: label })} agent="opencode"
    messages={view} results={results} hasEarlier={hasEarlier} onLoadEarlier={loadEarlier}
    renderMessage={(m, i) => <ChatMessage key={m.id || i} m={m} results={results} side="opencode" />}
    pending={pending ? <Typing color={CODEX_ACCENT} /> : undefined}
    busy={pending} active={active}
  />
})
