import { describe, it, expect } from 'vitest'
import { goalFromPane, modeChoices, modeFromPane, paneMode, plusGroups } from './composer-plus'
import { toAgentStatus, toMode } from './status'

// 面板文案不进这一层：测试的 t 只翻译认得的模式名，其余原样退回——
// 「认不出的模式 id 原样显示」这条正是靠这个差别测的
const t = (k: string) => (k === 'chat.mode.plan' ? '计划模式' : k)

describe('plusGroups', () => {
  it('没有 agent（纯终端）时只剩「带进这条消息」：那几条都是发给 agent 的', () => {
    const g = plusGroups({ t })
    expect(g.map((x) => x.id)).toEqual(['bring'])
  })

  it('两端都认 /model、/compact、/review 与 Shift+Tab；目标是 Codex 独有的', () => {
    const ids = (agent: 'claude' | 'codex') =>
      plusGroups({ agent, t }).flatMap((x) => x.rows.map((r) => r.id))
    expect(ids('claude')).toEqual(['files', 'mode', 'model', 'compact', 'review'])
    expect(ids('codex')).toEqual(['files', 'mode', 'goal', 'model', 'compact', 'review'])
  })

  it('目标卡住 / 额度用尽才上警戒色——「它停了而你不知道」才值得一支黄', () => {
    const goalRow = (goal: any) => plusGroups({ agent: 'codex', goal, t })[1].rows[1]
    expect(goalRow('stalled')).toMatchObject({ id: 'goal', value: 'chat.plus.goal.stalled', tone: 'var(--warn)' })
    expect(goalRow('budget').tone).toBe('var(--warn)')
    expect(goalRow('achieved').tone).toBeUndefined()
    expect(goalRow(undefined).value).toBeUndefined()
  })

  it('模式那行带当前档与色点——菜单最该回答的是「现在是哪一档」', () => {
    const g = plusGroups({ agent: 'claude', status: toAgentStatus({ mode: 'plan' }), t })
    const mode = g[1].rows[0]
    expect(mode).toMatchObject({ id: 'mode', value: '计划模式', dot: 'var(--accent)', kbd: 'Shift+Tab' })
  })

  it('没见过的模式 id 原样显示，不把 i18n key 画到面板上', () => {
    const g = plusGroups({ agent: 'codex', status: toAgentStatus({ mode: 'brand-new-mode' }), t })
    expect(g[1].rows[0].value).toBe('brand-new-mode')
  })

  it('正在等这次切换生效：值换成「切换中」，色点收起来（免得看着像已经切好了）', () => {
    const g = plusGroups({ agent: 'claude', status: toAgentStatus({ mode: 'plan' }), modePending: true, t })
    expect(g[1].rows[0]).toMatchObject({ value: 'chat.plus.modeWaiting', dot: undefined, pending: true })
  })

  it('压缩那行写着现在用了多少，快满了才上色', () => {
    const at = (used: number) =>
      plusGroups({ agent: 'claude', status: toAgentStatus({ used, window: 100 }), t })[1].rows[2]
    expect(at(27)).toMatchObject({ value: '27%', tone: undefined })
    expect(at(88)).toMatchObject({ value: '88%', tone: 'var(--warn)' })
    expect(at(97)).toMatchObject({ value: '97%', tone: 'var(--danger)' })
  })

  it('还不知道模型/占用时那两行留空，不画「—」占位', () => {
    const rows = plusGroups({ agent: 'claude', t })[1].rows
    expect(rows[1].value).toBeUndefined()
    expect(rows[2].value).toBeUndefined()
  })

  it('上传中那行禁用；没有 Git 面板就不出现那一组', () => {
    const g = plusGroups({ agent: 'claude', uploading: true, t })
    expect(g[0].rows[0].disabled).toBe(true)
    expect(g.some((x) => x.id === 'goto')).toBe(false)
    const withGit = plusGroups({ agent: 'claude', canGit: true, t })
    expect(withGit[withGit.length - 1]).toMatchObject({ id: 'goto' })
  })
})

// 真实抓屏（Claude Code 2.1.261 / Codex 0.149.0 的页脚）
const CLAUDE_FOOTER = `› 
  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt · ← for agents · /diff to hide diff`
const CODEX_FOOTER = `› Ask Codex to do anything
  gpt-5.6-sol medium · ~/codes/ttmux    Plan mode (shift+tab to cycle)`

describe('modeFromPane', () => {
  it('从页脚那枚片读当前档：转录里那份要等下一条消息才更新', () => {
    expect(modeFromPane(CLAUDE_FOOTER)).toBe('auto')
    expect(modeFromPane(CLAUDE_FOOTER.replace('auto mode on', 'accept edits on'))).toBe('acceptEdits')
    expect(modeFromPane(CLAUDE_FOOTER.replace('auto mode on', 'plan mode on'))).toBe('plan')
    expect(modeFromPane(CLAUDE_FOOTER.replace('auto mode on', 'bypass permissions'))).toBe('bypassPermissions')
    expect(modeFromPane(CODEX_FOOTER)).toBe('plan')
    // 「每步都问」那一档 Claude 不写 shift+tab 提示，只剩片前面那个 ⏸ 当锚
    expect(modeFromPane('  ⏸ manual mode on · PR #250 · ← for agents')).toBe('manual')
  })

  it('只认带 shift+tab 提示的那一行——正文里说到 "plan mode" 不算', () => {
    expect(modeFromPane('我建议先切到 plan mode 再看\n然后再说')).toBeUndefined()
    // Codex 的默认档没有那枚片：读不到就是读不到，交回转录那份去说
    expect(modeFromPane('› Ask Codex to do anything\n  gpt-5.6-sol medium · ~/codes/ttmux')).toBeUndefined()
  })

  it('末尾一串空行不能把页脚藏掉——Codex 的界面画在上半屏，抓下来后面全是空的', () => {
    expect(modeFromPane(CODEX_FOOTER + '\n'.repeat(14))).toBe('plan')
  })

  it('翻上去还留着旧页脚时，以最后一次为准', () => {
    const stale = CLAUDE_FOOTER.replace('auto mode on', 'plan mode on')
    expect(modeFromPane(stale + '\n' + CLAUDE_FOOTER)).toBe('auto')
  })
})

describe('plusGroups：画面读到的档盖过转录', () => {
  it('刚按完 Shift+Tab，转录还停在旧档，面板要显示新的那个', () => {
    const g = plusGroups({ agent: 'claude', status: toAgentStatus({ mode: 'auto' }), mode: toMode('plan'), t })
    expect(g[1].rows[0]).toMatchObject({ value: '计划模式', dot: 'var(--accent)' })
  })
})

describe('paneMode / modeChoices', () => {
  it('Codex 的默认档不画那枚片：读到画面、没有片，就是默认档', () => {
    expect(paneMode('› Ask Codex to do anything\n  gpt-5.6-sol medium', 'codex')).toBe('default')
    // Claude 每一档都画：读不出就是真读不出，交回转录那份，不猜
    expect(paneMode('› \n  some other footer', 'claude')).toBeUndefined()
    // 压根没读到画面（capture 失败/空）时两端都不许瞎报
    expect(paneMode('   ', 'codex')).toBeUndefined()
  })

  it('可选的档按端给；当前这档一定在列（老版本报 default，新版本报 auto）', () => {
    // 按「能自己动多少」从少到多排，不照抄 CLI 的轮换顺序
    expect(modeChoices('claude')).toEqual(['plan', 'manual', 'auto', 'acceptEdits'])
    expect(modeChoices('codex')).toEqual(['plan', 'default'])
    // 启动时开的 bypassPermissions 不在常规列表里，但真在那一档时得看得见
    expect(modeChoices('claude', 'bypassPermissions')[0]).toBe('bypassPermissions')
    expect(modeChoices('codex', 'plan')).toEqual(['plan', 'default'])
  })
})

describe('goalFromPane', () => {
  it('长跑目标停下来了，页脚会说——那句话就是行尾那截状态', () => {
    expect(goalFromPane('Goal paused (/goal resume)')).toBe('paused')
    expect(goalFromPane('Goal stalled (/goal resume)')).toBe('stalled')
    expect(goalFromPane('Goal hit usage limits (/goal resume)')).toBe('budget')
    expect(goalFromPane('  Goal achieved  ')).toBe('achieved')
    expect(goalFromPane('› Ask Codex to do anything')).toBeUndefined()
  })
})

it('Pi exposes supported model and compact controls without Claude modes or review', () => {
  const rows = plusGroups({ agent: 'pi', t: key => key }).flatMap(group => group.rows.map(row => row.id))
  expect(rows).toEqual(['files', 'model', 'compact'])
})
