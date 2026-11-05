// 任务原文置顶，工作区准备与能力说明随后补充。

import { api } from '../../api'
import { nodeApi } from '../cluster/node-url'

export type BriefWhere =
  | { kind: 'new'; path: string; base: string; branch: string }
  | { kind: 'adopt'; path: string; base: string; branch: string }
  | { kind: 'repo'; path: string; branch: string }
  | { kind: 'plain'; path: string }

type T = (key: string, vars?: Record<string, unknown>) => string

/** 只有前言（没有任务时不拼，调用方直接起 agent 不带参数） */
export function briefPreamble(where: BriefWhere, sess: string, autoReview: boolean, t: T): string {
  const head =
    where.kind === 'new' ? t('session.wt.briefNew', { path: where.path, base: where.base, branch: where.branch, sess })
      : where.kind === 'adopt' ? t('session.wt.briefAdopt', { path: where.path, branch: where.branch, base: where.base, sess })
        : where.kind === 'repo' ? t('session.wt.briefRepo', { path: where.path, branch: where.branch, sess })
          : t('session.wt.briefPlain', { path: where.path, sess })
  return head + (autoReview ? t('session.wt.briefReview') : '')
}

export async function loadAgentCapabilities(): Promise<string> {
  const fileBase = nodeApi('/file')
  const fileRawBase = nodeApi('/file/raw')
  const fileServeBase = nodeApi('/file/serve')
  const response = await api('GET', '/agent/capabilities')
  return String(response.data?.content || '').split('{{FILE_BASE}}').join(fileBase)
    .split('{{FILE_RAW_BASE}}').join(fileRawBase)
    .split('{{FILE_SERVE_BASE}}').join(fileServeBase).trim()
}

export function taskWithCapabilities(task: string, t: T, capabilities: string): string {
  const guide = capabilities.trim()
  return `${t('session.wt.briefTask')}\n\n${task.trim()}${guide ? `\n\n${guide}` : ''}`
}

/** 任务为空不发送准备事项或能力说明。 */
export function kickoffBrief(where: BriefWhere, sess: string, autoReview: boolean, task: string, t: T, capabilities = ''): string {
  const body = task.trim()
  if (!body) return ''
  const instructions = `${t('session.wt.briefSetup')}\n\n${briefPreamble(where, sess, autoReview, t)}`
  return taskWithCapabilities(body, t, [instructions, capabilities.trim()].filter(Boolean).join('\n\n'))
}
