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
    'session.wt.briefTask': '# 任务：',
    'session.wt.briefSetup': '# 开工准备',
    'session.wt.briefSession': '当前会话（稳定 ID）：`{sess}`。',
  }
  return (table[k] || k).replace(/\{(\w+)\}/g, (_, n) => String(v?.[n] ?? ''))
}
const where = { kind: 'new' as const, path: '/w', base: 'main', branch: 'tmp' }

describe('开工简报', () => {
  it('任务标题和原文位于第一段，准备事项随后', () => {
    const b = kickoffBrief(where, 's1', false, '把 /pools 改成 /pools/{id}', t)
    expect(b).toBe('# 任务：\n\n把 /pools 改成 /pools/{id}\n\n# 开工准备\n\n当前会话（稳定 ID）：`s1`。\n\n开工前先做三件事，做完再开始下面的任务：\n1. 工作区 /w（从 main 切，占位分支 tmp）\n3. roami session rename s1 <新名字>')
  })
  it('去掉首尾空白，保留任务内的多行、标题与代码', () => {
    const body = '第一行\n# 用户标题\n```sh\necho task\n```'
    expect(kickoffBrief(where, 's1', false, `  ${body}  \n`, t).startsWith(`# 任务：\n\n${body}\n\n# 开工准备`)).toBe(true)
  })
  it('没有任务就不拼准备事项或能力说明', () => {
    expect(kickoffBrief(where, 's1', true, '   ', t, '# Roami 会话能力')).toBe('')
  })
  it('互审说明归于准备事项，仍位于任务原文之后', () => {
    const b = kickoffBrief({ kind: 'plain', path: '/p' }, 's2', true, 'x', t)
    expect(b).toBe('# 任务：\n\nx\n\n# 开工准备\n\n当前会话（稳定 ID）：`s2`。\n\n你在 /p，会话 s2\n另有互审。')
  })
  it('能力说明跟随准备事项，不能抢占任务的首段', () => {
    const b = kickoffBrief(where, 's1', false, '生成视频', t, '# Roami 会话能力\n\n文件入口：/api/file')
    expect(b.startsWith('# 任务：\n\n生成视频\n\n# 开工准备')).toBe(true)
    expect(b.endsWith('# Roami 会话能力\n\n文件入口：/api/file')).toBe(true)
  })
  it.each([null, 'remote node'])('从当前节点 %s 读取模板，并将所有文件入口绑定到该节点', async (node) => {
    setCurrentNode(node)
    const prefix = node ? '/n/remote%20node' : ''
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: { content: '文档 {{FILE_BASE}}/tmp/report.md 图片 {{FILE_BASE}}/tmp/demo.png raw {{FILE_RAW_BASE}}?path=x HTML {{FILE_SERVE_BASE}}/tmp/demo.html' },
    }), { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await loadAgentCapabilities()).toBe(`文档 ${prefix}/api/file/tmp/report.md 图片 ${prefix}/api/file/tmp/demo.png raw ${prefix}/api/file/raw?path=x HTML ${prefix}/api/file/serve/tmp/demo.html`)
    expect(fetchMock.mock.calls[0][0]).toBe(`${prefix}/api/agent/capabilities`)
  })
  it('文件启动 Agent 也携带能力说明和原任务', () => {
    expect(taskWithCapabilities('查看 /tmp/demo.md', t, 'Roami 能力')).toBe('# 任务：\n\n查看 /tmp/demo.md\n\nRoami 能力')
  })
  it('自定义能力为空时仍保留统一执行、回报和产物约定', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: { executionGuide: '# 执行约定\n\n## 产物交付\n\n# 回报通道', content: '' },
    }), { headers: { 'Content-Type': 'application/json' } })))
    const guide = await loadAgentCapabilities()
    const brief = kickoffBrief(where, 's1', false, '生成报告', t, guide)
    expect(brief).toContain('# 开工准备')
    expect(brief).toContain('# 执行约定\n\n## 产物交付\n\n# 回报通道')
  })
  it('模板不可读时中止提交，调用方不会创建空会话', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'CAPABILITIES_READ_ERROR' },
    }), { status: 500, headers: { 'Content-Type': 'application/json' } })))
    await expect(loadAgentCapabilities()).rejects.toThrow('CAPABILITIES_READ_ERROR')
  })
})
