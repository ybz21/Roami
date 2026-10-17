// Codex 对话面板（容器）：拉 codex rollout 转录 → 交给 ChatShell 渲染。
// 消息渲染在 chat/Message（与 Claude 共用一份，只差 side），工具渲染在 chat/tool-render。
import { memo, useMemo } from 'react'
import { ChatShell } from './ChatShell'
import { Typing } from './blocks'
import { ChatMessage, CODEX_ACCENT } from './Message'
import { useTranscript, isPending, pairToolResults } from './useTranscript'
import { buildTaskIndex } from './tasks'
import { toAgentStatus } from './status'
import { deriveFromMessages } from './status-derive'
import { useSessionLabel } from '../sessions/session-label'
import { useI18n } from '../../i18n'

// memo：父层（TerminalPane）任何 setState 都会重渲，N 个常驻对话不该跟着一起重算
export default memo(function CodexChat({ name, file, onOpenFile, onOpenGit, active }: { name: string; file?: string; onOpenFile?: (path: string, line?: number) => void; onOpenGit?: () => void; active?: boolean }) {
  const { t } = useI18n()
  const label = useSessionLabel(name)
  const { msgs, err, status: raw, hasEarlier, loadEarlier, resolvedFile } = useTranscript(name, file, 'codex-transcript', active === false ? 6000 : 1500)
  const { results, view } = useMemo(() => pairToolResults(msgs), [msgs])
  const pending = isPending(view)
  // TaskUpdate 只给 {taskId,status}，标题在更早那次 TaskCreate 的结果里 —— 跨消息扫一遍才接得上
  const tasks = useMemo(() => buildTaskIndex(view, results), [view, results])
  // 失败数与时长后端给不了（它只增量扫新行），前端手里是完整消息流，数一遍就有
  const derived = useMemo(() => deriveFromMessages(view), [view])
  const status = useMemo(() => ({ ...toAgentStatus(raw, tasks), errors: derived.errors, elapsed: derived.elapsed }), [raw, tasks, derived])

  return (
    <ChatShell
      emptyHint={resolvedFile !== undefined && msgs.length === 0 ? t('chat.noTranscriptYet') : undefined}
      name={name} accent={CODEX_ACCENT} error={err} onOpenFile={onOpenFile} tasks={tasks} status={status} onOpenGit={onOpenGit} lastErrorId={derived.lastErrorId}
      placeholder={t('chat.sendTo', { name: label })} agent="codex"
      messages={view} results={results} hasEarlier={hasEarlier} onLoadEarlier={loadEarlier}
      renderMessage={(m, i) => <ChatMessage key={m.id || i} m={m} results={results} side="codex" />}
      pending={pending ? <Typing color={CODEX_ACCENT} /> : undefined}
      busy={pending} active={active}
    />
  )
})
