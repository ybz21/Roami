import type { AgentMessage } from '../../agent/agent-protocol'
import { configurationOf, type Configuration, type Workspace } from './okr-workspace'

export const okrContextMarker = '\n\n<roami-okr-context>\n'
export function displayOkrMessage(text: string, content?: AgentMessage['content']) {
  if (content?.okrContext?.version === 1) return text
  const start = text.indexOf(okrContextMarker)
  if (start < 0 || !text.endsWith('\n</roami-okr-context>')) return text
  const tail = text.slice(start + okrContextMarker.length)
  const line = tail.indexOf('\n')
  try {
    const snapshot = JSON.parse(tail.slice(0, line))
    if (snapshot.projectId && tail.slice(line + 1).startsWith('你是此 OKR 固定的主智能体；')) return text.slice(0, start)
  } catch { /* Literal tags are user text. */ }
  return text
}
export function prepareOkrContext(text: string, draft: Configuration, workspace: Workspace | null, supported: boolean) {
  if (text.trim().startsWith('/')) return undefined
  const definition = configurationOf(draft)
  const changed = !workspace || JSON.stringify(definition) !== JSON.stringify(configurationOf(workspace))
  if (!supported) {
    if (changed) throw new Error('OKR_MESSAGE_CONTEXT_UNSUPPORTED')
    return undefined
  }
  const context = { version: 1 as const, revision: workspace?.revision || 0, ...(changed ? { draft: definition } : {}) }
  if (new TextEncoder().encode(JSON.stringify(context)).length > 65536) throw new Error('OKR_MESSAGE_CONTEXT_TOO_LARGE')
  return context
}
