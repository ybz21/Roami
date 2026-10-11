// detectPrompt 的回归用例。重点是**窄屏**：手机 attach 后 tmux 窗格常只剩 40 多列，
// Claude 的选项会折成五六行，早期按「行距 ≤3」分组会把每个选项拆成孤岛 → 手机上根本不弹提问框。
import { describe, it, expect } from 'vitest'
import { advancePromptSignal, detectPrompt } from './prompt'

// 宽屏：选项彼此紧挨
const WIDE = `
   Select model
   Switch between Claude models. Your pick becomes the default for new sessions.
     1. Default (recommended)  Opus 5 with 1M context · Best for everyday tasks
   ❯ 2. Opus (1M context) ✔    Opus 5 with 1M context · Best for everyday tasks
     3. Fable                  Fable 5 · Most capable for your hardest tasks
   Enter to set as default · Esc to cancel
`

// 窄屏（47 列，真机抓的）：每个选项后面跟 4 行续行，选项之间隔 5 行
const NARROW = `
   Select model
   Switch between Claude models. Your pick
   becomes the default for new sessions. For
   other/previous model names, specify with
   --model.

     1. Default (recommende…  Opus 5 with 1M
                              context ·
                              Best for
                              everyday,
                              complex tasks
   ❯ 2. Opus (1M context) ✔   Opus 5 with 1M
                              context ·
                              Best for
                              everyday,
                              complex tasks
     3. Fable                 Fable 5 · Most
                              capable for
                              your hardest   ↓
`

// 普通编号列表：没有游标、也没有确认类关键词，不该误判成选择框
const PLAIN_LIST = `
   Here is what I changed:
     1. renamed the helper
     2. added a test
     3. updated the docs
   Done.
`

// Agent 正常工作时最常见的误报：编号总结里包含 run / command / continue，
// 这些只是正文，不是一个正在等待用户操作的选择框。
const COMMAND_LIST = `
   Running implementation work…
     1. Run the formatter command
     2. Continue with the typecheck
     3. Write the result > report.txt
   Working…
`

const NO_CURSOR_PROMPT = `
   Are you sure you want to proceed?
     1. Yes, continue
     2. No, go back
   Enter to confirm · Esc to cancel
`

const QUOTED_LIST = `
   Documentation example:
   > 1. Run the command
   > 2. Continue editing
   Done.
`

// Claude 起手的信任确认（真机 capture）：选项没有编号，只有一个 ❯ 游标。
// 新建 worktree 的会话第一屏就是它——认不出来的话对话面板里什么都没有。
const TRUST = `
 Accessing workspace:

 /tmp/probe

 Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known open source
 project, or work from your team). If not, take a moment to review what's in this folder first.

 Claude Code'll be able to read, edit, and execute files here.

 ⚠ This folder pre-approves 1 tool permission in .claude/settings.local.json:
   Bash(git log *)
 These will apply without asking. Only proceed if you trust this configuration.

 Security guide

 ❯ No, exit
   Yes, I trust this folder

 Enter to confirm · Esc to cancel
`

// 输入框那行也是 ❯ 打头，底下跟着状态栏：没有对齐的兄弟项、也没有确认提示，不能当选择框
const COMPOSER = `
 ✻ Sautéed for 4m · done 7:50 PM

 ❯ 帮我在配置中心配一个 logos 试试
   ⏵⏵ auto mode on · 1 shell · ← for agents
`

const NUMBERED_COMPOSER = `
 Worked for 56m 58s
› 1. 手机支持下拉刷新页面
  2. 下载 App 要有能够感知到的地方
 GPT-6-Sol medium · ← for agents · ? for shortcuts
`

// 窄屏（手机 attach 后 tmux 只剩四十来列）：提问被折成五行，离选项十几行远。
const TRUST_NARROW = `
 /tmp/trust-probe-e1

 Quick safety check: Is this a project you
 created or one you trust? (Like your own
 code, a well-known open source project, or
 work from your team). If not, take a moment
 to review what's in this folder first.

 Claude Code'll be able to read, edit, and
 execute files here.

 ⚠ This folder pre-approves 1 tool permission
 in .claude/settings.local.json:
   Bash(git log *)
 These will apply without asking. Only proceed
 if you trust this configuration.

 Security guide

 ❯ No, exit
   Yes, I trust this folder

 Enter to confirm · Esc to cancel
`

describe('detectPrompt', () => {
  it('宽屏选择框：识别出全部选项与当前游标', () => {
    const p = detectPrompt(WIDE)
    expect(p?.kind).toBe('select')
    expect(p?.choices.map((c) => c.num)).toEqual([1, 2, 3])
    expect(p?.choices.find((c) => c.selected)?.num).toBe(2)
  })

  it('窄屏折行选择框：选项隔了 5 行也要认出来（手机回归）', () => {
    const p = detectPrompt(NARROW)
    expect(p?.kind).toBe('select')
    expect(p?.choices.map((c) => c.num)).toEqual([1, 2, 3])
    expect(p?.choices.find((c) => c.selected)?.num).toBe(2)
  })

  it('y/n 提示走兜底分支', () => {
    expect(detectPrompt('Overwrite existing file? (y/n)')?.kind).toBe('yesno')
    expect(detectPrompt('Documentation: answer (y/n)\nDone.')).toBeNull()
  })

  it('普通编号列表不误判', () => {
    expect(detectPrompt(PLAIN_LIST)).toBeNull()
  })

  it('包含 run/command/continue 和重定向符的工作输出不误判', () => {
    expect(detectPrompt(COMMAND_LIST)).toBeNull()
    expect(detectPrompt(QUOTED_LIST)).toBeNull()
  })

  it('没有可见游标时，明确提问和操作提示组合仍可识别', () => {
    expect(detectPrompt(NO_CURSOR_PROMPT)?.kind).toBe('select')
  })

  it('无编号的信任确认框：认出两个选项和当前游标', () => {
    const p = detectPrompt(TRUST)
    expect(p?.kind).toBe('select')
    expect(p?.numbered).toBe(false)
    expect(p?.choices.map((c) => c.label)).toEqual(['No, exit', 'Yes, I trust this folder'])
    expect(p?.choices.find((c) => c.selected)?.num).toBe(1)
    expect(p?.question).toContain('trust')
  })

  it('窄屏折行的信任确认框：提问跨五行也要拼回来', () => {
    const p = detectPrompt(TRUST_NARROW)
    expect(p?.numbered).toBe(false)
    expect(p?.choices.map((c) => c.label)).toEqual(['No, exit', 'Yes, I trust this folder'])
    expect(p?.question).toContain('Quick safety check')
  })

  it('输入框那行 ❯ 不当选择框', () => {
    expect(detectPrompt(COMPOSER)).toBeNull()
    expect(detectPrompt(NUMBERED_COMPOSER)).toBeNull()
  })

  it('空屏返回 null', () => {
    expect(detectPrompt('')).toBeNull()
  })

  it('待确认状态需要连续两次相同采样才切换', () => {
    const firstPositive = advancePromptSignal(undefined, true)
    expect(firstPositive.stable).toBe(false)
    const confirmedPositive = advancePromptSignal(firstPositive, true)
    expect(confirmedPositive.stable).toBe(true)
    const firstNegative = advancePromptSignal(confirmedPositive, false)
    expect(firstNegative.stable).toBe(true)
    expect(advancePromptSignal(firstNegative, false).stable).toBe(false)
  })
})
