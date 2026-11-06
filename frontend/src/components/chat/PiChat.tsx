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

export default memo(function PiChat({ name, onOpenFile, onOpenGit, active, onSend }: { name: string; onOpenFile?: (path: string, line?: number) => void; onOpenGit?: () => void; active?: boolean; onSend?: (text: string) => Promise<void> }) {
  const { t } = useI18n(), label = useSessionLabel(name)
  const { msgs, err, status: raw, hasEarlier, loadEarlier, resolvedFile, serverPending } = useTranscript(name, undefined, 'pi-transcript', active === false ? 6000 : 1500)
  const { results, view } = useMemo(() => pairToolResults(msgs), [msgs])
  const tasks = useMemo(() => buildTaskIndex(view, results), [view, results])
  const derived = useMemo(() => deriveFromMessages(view), [view])
  const status = useMemo(() => ({ ...toAgentStatus(raw, tasks), errors: derived.errors, elapsed: derived.elapsed }), [raw, tasks, derived])
  return <ChatShell name={name} accent={CODEX_ACCENT} agent="pi" placeholder={t('chat.sendTo', { name: label })}
    emptyHint={resolvedFile !== undefined && !msgs.length ? t('chat.noTranscriptYet') : undefined}
    error={err} onOpenFile={onOpenFile} onOpenGit={onOpenGit} tasks={tasks} status={status} lastErrorId={derived.lastErrorId}
    messages={view} results={results} hasEarlier={hasEarlier} onLoadEarlier={loadEarlier}
    renderMessage={(m, i) => <ChatMessage key={m.id || i} m={m} results={results} side="pi" />}
    pending={serverPending ? <Typing color={CODEX_ACCENT} /> : undefined} busy={serverPending} active={active} onSend={onSend} />
})
