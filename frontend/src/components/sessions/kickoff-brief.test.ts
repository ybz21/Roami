import { describe, expect, it } from 'vitest'
import { kickoffBrief } from './kickoff-brief'

const t = (k: string, v?: Record<string, unknown>) => {
  const table: Record<string, string> = {
    'session.wt.briefNew': '开工前先做三件事，做完再开始下面的任务：\n1. 工作区 {path}（从 {base} 切，占位分支 {branch}）\n3. ttmux rename {sess} <新名字>',
    'session.wt.briefPlain': '你在 {path}，会话 {sess}',
    'session.wt.briefReview': '\n另有互审。',
    'session.wt.briefTask': '任务：',
  }
  return (table[k] || k).replace(/\{(\w+)\}/g, (_, n) => String(v?.[n] ?? ''))
}
const where = { kind: 'new' as const, path: '/w', base: 'main', branch: 'tmp' }

describe('开工简报', () => {
  it('任务本体前有明确的「任务：」标题', () => {
    // 前言说「做完再开始下面的任务」，下面紧跟用户原话而没有标题时，
    // agent 容易把需求读成第 3 步的续文
    const b = kickoffBrief(where, 's1', false, '把 /pools 改成 /pools/{id}', t)
    expect(b).toMatch(/ttmux rename s1 <新名字>\n\n任务：\n把 \/pools 改成/)
  })
  it('任务原文前后空白去掉，内容原样保留', () => {
    expect(kickoffBrief(where, 's1', false, '  第一行\n第二行  \n', t).endsWith('任务：\n第一行\n第二行')).toBe(true)
  })
  it('没有任务就不拼 —— 调用方直接起 agent', () => {
    expect(kickoffBrief(where, 's1', false, '   ', t)).toBe('')
  })
  it('互审那句跟在前言后面、标题前面', () => {
    const b = kickoffBrief({ kind: 'plain', path: '/p' }, 's2', true, 'x', t)
    expect(b).toBe('你在 /p，会话 s2\n另有互审。\n\n任务：\nx')
  })
})
