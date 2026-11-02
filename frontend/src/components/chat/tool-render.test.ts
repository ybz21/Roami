import { describe, it, expect } from 'vitest'
import { commandFromRaw, editParts, extractCommand, toolStatus } from './tool-render'
import { shortPath } from './tool-parts'
import type { Block } from './types'

const result = (text: string, isError = false): Block => ({ kind: 'tool_result', text, isError })

it('OpenCode edit 的 camelCase 入参能画出前后差异', () => {
  expect(editParts('edit', { path: 'src/a.ts', oldString: 'before', newString: 'after' })).toEqual({
    path: 'src/a.ts', oldText: 'before', newText: 'after', isNew: false,
  })
})

describe('extractCommand', () => {
  it('Claude 的字符串命令原样返回', () => {
    expect(extractCommand({ command: 'npm run typecheck' })).toBe('npm run typecheck')
  })

  it('Codex 的 bash -lc 外壳只取真正的命令', () => {
    expect(extractCommand({ command: ['bash', '-lc', 'npm test'] })).toBe('npm test')
    expect(extractCommand({ command: ['sh', '-c', 'ls | wc -l'] })).toBe('ls | wc -l')
    expect(extractCommand({ command: ['zsh', '-lic', 'echo hi'] })).toBe('echo hi')
  })

  it('不是外壳形式的数组按空格拼，不拼成逗号', () => {
    expect(extractCommand({ command: ['ls', '-la', '/tmp'] })).toBe('ls -la /tmp')
    expect(extractCommand({ command: ['bash', 'script.sh'] })).toBe('bash script.sh')
  })

  it('认 cmd / argv 两个别名', () => {
    expect(extractCommand({ cmd: 'pwd' })).toBe('pwd')
    expect(extractCommand({ argv: ['git', 'status'] })).toBe('git status')
  })

  it('拿不到就给空串，不抛', () => {
    expect(extractCommand(null)).toBe('')
    expect(extractCommand({})).toBe('')
  })
})

describe('commandFromRaw（后端截断了 JSON 时的兜底）', () => {
  it('JSON 被 clip 截断后照样抠得出命令，不再渲染成裸 JSON', () => {
    // 后端 clip() 在 6000 字处硬切，尾巴上的引号/括号全没了
    const truncated = '{"command":"cat > /tmp/pr.md <<\'EOF\'\\n一屏对话里工具调用占了大半'
    expect(JSON.parse.bind(null, truncated)).toThrow()   // 先确认它确实解析不了
    expect(commandFromRaw(truncated)).toBe("cat > /tmp/pr.md <<'EOF'\n一屏对话里工具调用占了大半")
  })

  it('转义序列还原：\\n \\t \\" \\\\ 与 \\uXXXX', () => {
    expect(commandFromRaw('{"command":"a\\nb\\tc \\"q\\" \\\\ \\u0041"}')).toBe('a\nb\tc "q" \\ A')
  })

  it('认 cmd 别名；没有命令字段就返回空串交给下一层兜底', () => {
    expect(commandFromRaw('{"cmd":"pwd"}')).toBe('pwd')
    expect(commandFromRaw('{"file_path":"/a"}')).toBe('')
    expect(commandFromRaw('not json at all')).toBe('')
  })
})

describe('toolStatus', () => {
  it('没有结果＝运行中', () => {
    expect(toolStatus(undefined)).toBe('running')
  })

  it('有结果且不报错＝成功', () => {
    expect(toolStatus(result('done'))).toBe('ok')
  })

  it('普通报错＝error', () => {
    expect(toolStatus(result('EACCES: permission denied', true))).toBe('error')
  })

  it('用户拒绝 / 中断算 denied，不染成故障红', () => {
    expect(toolStatus(result("The user doesn't want to take this action", true))).toBe('denied')
    expect(toolStatus(result('[Request interrupted by user]', true))).toBe('denied')
    expect(toolStatus(result('用户拒绝了该操作', true))).toBe('denied')
  })
})

describe('shortPath', () => {
  it('短路径原样', () => {
    expect(shortPath('src/App.tsx')).toBe('src/App.tsx')
  })

  it('长路径截头留尾：扔掉 /home/ai/… 那截，保住最近几层目录', () => {
    const p = '/home/ai/codes/ttmux/frontend/src/chat/tool-render.tsx'
    const out = shortPath(p)
    expect(out.startsWith('…/')).toBe(true)
    expect(out.endsWith('/chat/tool-render.tsx')).toBe(true)
    expect(out).not.toContain('/home/')
    expect(out.length).toBeLessThanOrEqual(44)
  })

  it('窄屏更短时至少留住文件名和一层目录', () => {
    const out = shortPath('/home/ai/codes/ttmux/frontend/src/App.tsx', 28)
    expect(out).toBe('…/ttmux/frontend/src/App.tsx')
  })

  it('文件名本身就超长时截尾巴（尾巴才是有用的那头）', () => {
    const out = shortPath('/a/' + 'x'.repeat(80) + '.ts', 20)
    expect(out.startsWith('…')).toBe(true)
    expect(out.endsWith('.ts')).toBe(true)
  })

  it('空值不抛', () => {
    expect(shortPath('')).toBe('')
  })
})


it('reads native file replacements with the same diff fields', () => {
  expect(editParts('Edit', { path: '/work/plan.md', oldText: 'draft', newText: 'ready' })).toEqual({ path: '/work/plan.md', oldText: 'draft', newText: 'ready', isNew: false })
})
