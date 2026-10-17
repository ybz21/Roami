import { afterEach, describe, expect, it, vi } from 'vitest'
import { kickoffBrief, loadAgentCapabilities, taskWithCapabilities } from './kickoff-brief'
import { setCurrentNode } from '../cluster/node-url'

afterEach(() => {
  vi.unstubAllGlobals()
  setCurrentNode(null)
})

const t = (k: string, v?: Record<string, unknown>) => {
  const table: Record<string, string> = {
    'session.wt.briefNew': '开工前先做三件事，做完再开始下面的任务：\n1. 工作区 {path}（从 {base} 切，占位分支 {branch}）\n3. roami session rename {sess} <新名字>',
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
    expect(b).toMatch(/roami session rename s1 <新名字>\n\n任务：\n把 \/pools 改成/)
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
  it('能力说明位于任务前，任务原文保持不变', () => {
    const b = kickoffBrief(where, 's1', false, '生成视频', t, '文件入口：/api/file/raw')
    expect(b).toMatch(/roami session rename s1 <新名字>\n\n文件入口：\/api\/file\/raw\n\n任务：\n生成视频$/)
  })
  it('从当前节点读取模板，并将所有文件入口绑定到该节点', async () => {
    setCurrentNode('remote node')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: { content: '图片 {{FILE_RAW_BASE}}?path=x 视频 {{FILE_RAW_BASE}}?path=y HTML {{FILE_SERVE_BASE}}/tmp/demo.html' },
    }), { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await loadAgentCapabilities()).toBe('图片 /n/remote%20node/api/file/raw?path=x 视频 /n/remote%20node/api/file/raw?path=y HTML /n/remote%20node/api/file/serve/tmp/demo.html')
    expect(fetchMock.mock.calls[0][0]).toBe('/n/remote%20node/api/agent/capabilities')
  })
  it('文件启动 Agent 也携带能力说明和原任务', () => {
    expect(taskWithCapabilities('查看 /tmp/demo.md', t, 'Roami 能力')).toBe('Roami 能力\n\n任务：\n查看 /tmp/demo.md')
  })
  it('模板不可读时中止提交，调用方不会创建空会话', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'CAPABILITIES_READ_ERROR' },
    }), { status: 500, headers: { 'Content-Type': 'application/json' } })))
    await expect(loadAgentCapabilities()).rejects.toThrow('CAPABILITIES_READ_ERROR')
  })
})
