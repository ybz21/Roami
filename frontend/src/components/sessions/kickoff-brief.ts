// 开工简报：新会话里 agent 收到的第一条消息 =「开工前先做几件事」+ 任务本体。
//
// 从前 NewSessionModal 和 TaskComposer 各拼一份，逐字重复，于是一起漏了同一样东西：
// 简报说「做完再开始下面的任务」，可下面紧跟的就是用户原话，**没有「任务：」标题**。
// 前面几步一长，agent 很容易把需求读成最后一步的续文。现在两边都走这里。

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
  const fileRawBase = nodeApi('/file/raw')
  const fileServeBase = nodeApi('/file/serve')
  const response = await api('GET', '/agent/capabilities')
  return String(response.data?.content || '').split('{{FILE_RAW_BASE}}').join(fileRawBase)
    .split('{{FILE_SERVE_BASE}}').join(fileServeBase).trim()
}

export function taskWithCapabilities(task: string, t: T, capabilities: string): string {
  const guide = capabilities.trim()
  return `${guide ? `${guide}\n\n` : ''}${t('session.wt.briefTask')}\n${task.trim()}`
}

/** 完整简报：前言、能力说明、任务原文。任务为空返回空串。 */
export function kickoffBrief(where: BriefWhere, sess: string, autoReview: boolean, task: string, t: T, capabilities = ''): string {
  const body = task.trim()
  if (!body) return ''
  return `${briefPreamble(where, sess, autoReview, t)}\n\n${taskWithCapabilities(body, t, capabilities)}`
}
