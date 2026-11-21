// 交互式选择框检测与响应 —— 供 ClaudeChat / CodexChat 专业渲染模式复用。
//
// 背景：Claude/Codex 的权限确认、选项菜单是终端 TUI 实时状态，不在 JSONL transcript 里，
// 所以对话面板渲染不出、也无从响应。这里从实时屏幕(capture，纯文本含 ❯/框线)解析出
// 选择框，渲染成可点按钮；点击经 POST /sessions/:name/keys 注入原始按键完成选择。
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Button, Modal, Space } from 'antd'
import { api } from '../api'
import { usePageActive } from '../page-activity'
import { currentNodeId, useCurrentNodeId } from './cluster/node-url'
import { readSessionScreen, useSessionScreen } from './terminal/session-screen'
import { useI18n } from '../i18n'
import { ArrowDown, ArrowUp, ChevronRight, DotIcon } from '../icons'

export interface Choice { num: number; label: string; selected: boolean }
/** numbered=false：选项没有 1./2. 编号，只能靠方向键挪游标（见 detectUnnumbered） */
export interface Prompt { kind: 'select' | 'yesno'; question: string; choices: Choice[]; numbered?: boolean }

const CURSOR_PREFIX = /^[❯➤▶►▸→›»☞◉●>]\s*/u           // 选中游标必须位于选项开头，不能匹配正文里的 > / ●
const LEAD = /^[\s│┃|╎┆┊╭╰├╞┝─━═]+/u                  // 行首方框线/竖线/空白
const TAIL = /[\s│┃|╎┆┊╮╯┤╡┥─━═]+$/u                  // 行尾同上
const OPT = /^(?:[❯➤▶►▸→›»☞◉●>]\s*)?(\d+)[.)]\s+(\S.*)$/u // [游标?] N. 文本
// 无可见游标时只接受“明确提问 + 操作提示”的组合。run/command/执行/命令太常见，
// Agent 的普通编号总结很容易命中，造成后台标签在“待确认/运行中”之间反复闪动。
const QUESTION = /(?:would you like|do you want|are you sure|should (?:we|i)|(?:proceed|allow|continue|overwrite|approve|trust).*[?？]|是否(?:继续|允许|确认|执行)|(?:继续|允许|确认|执行).*[?？])/i
const ACTION_HINT = /(?:(?:enter|return).*(?:select|confirm|continue|submit|accept)|(?:esc|escape).*(?:cancel|back)|(?:回车|enter).*(?:选择|确认|继续)|(?:按|press).*(?:y|n|yes|no).*(?:确认|confirm))/i
const MENU_TITLE = /^(?:select|choose|pick)\b|^which\b.*[?？]|^(?:请选择|选择(?:模型|版本|选项)|请确认|是否.*[?？])/i
const CURSOR_ONLY = /^(\s*)[❯➤▶►▸›»](\s+)(\S.*)$/u        // [缩进]游标 文本（无编号选项）
const BOX_LEAD = /^\s*[│┃|╎┆┊╭╰├╞┝─━═]+/u                  // 只吃框线与它前面的空白，缩进要留着
const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]/g
const CTRL = /[\x00-\x08\x0b-\x1f\x7f]/g
const stripCtl = (s: string) => s.replace(ANSI, '').replace(CTRL, '')
const clean = (s: string) => stripCtl(s).replace(LEAD, '').replace(TAIL, '').trim()
// 同 clean，但**保留行首缩进**：无编号选择框全靠「文本起始列对齐」认出同一组选项。
const inner = (s: string) => stripCtl(s).replace(BOX_LEAD, '').replace(TAIL, '')

// 从一屏纯文本里解析当前是否有交互式选择框；没有则返回 null
export function detectPrompt(capture: string): Prompt | null {
  const lines = stripCtl(capture || '').replace(/\r/g, '').split('\n')
  type P = { num: number; label: string; selected: boolean; idx: number }
  const opts: P[] = []
  lines.forEach((raw, idx) => {
    const m = clean(raw).match(OPT)
    if (m) opts.push({ num: Number(m[1]), label: m[2].trim(), selected: CURSOR_PREFIX.test(clean(raw)), idx })
  })
  // 取最后一组选项。绑定条件是「编号正好接上」而不是单纯挨得近：手机 attach 后 tmux 窗格常只有
  // 40 多列，Claude 的选项被折成五六行，按行距卡 ≤3 会把每个选项都拆成孤岛 → 一条都识别不出来
  // （表现为手机上根本不弹提问框）。编号连续性本身就足够防误判，行距只留一个宽松上限兜底。
  const g: P[] = []
  for (let i = opts.length - 1; i >= 0; i--) {
    if (!g.length) { g.unshift(opts[i]); continue }
    if (opts[i].num === g[0].num - 1 && g[0].idx - opts[i].idx <= 12) g.unshift(opts[i])
    else break
  }
  // 必须是从 1 起的连续编号、至少两项 —— 否则当普通编号列表，不误判
  const sequential = g.length >= 2 && g.every((o, k) => o.num === k + 1)
  if (sequential && nearScreenEnd(lines, g[g.length - 1].idx)) {
    const qlines: string[] = []
    for (let i = g[0].idx - 1; i >= 0 && g[0].idx - i <= 6; i--) {
      const c = clean(lines[i])
      if (!c) { if (qlines.length) break; else continue }
      if (OPT.test(c)) continue
      qlines.unshift(c)
      if (qlines.length >= 3) break
    }
    const question = qlines.join(' ').trim()
    const windowText = lines.slice(Math.max(0, g[0].idx - 8), Math.min(lines.length, g[g.length - 1].idx + 3)).map(clean).join(' ')
    // Codex 的普通输入框也能以「› 1.」开头，不能仅凭游标把后续编号正文当菜单。
    const selectedCount = g.filter((o) => o.selected).length
    const before = lines.slice(Math.max(0, g[0].idx - 20), g[0].idx).map(clean)
    const menuEvidence = ACTION_HINT.test(windowText) || before.some((line) => MENU_TITLE.test(line))
    if ((selectedCount === 1 && menuEvidence) || (QUESTION.test(question) && ACTION_HINT.test(windowText))) {
      const choices = g.map((o) => ({ num: o.num, label: o.label, selected: o.selected }))
      if (!choices.some((c) => c.selected)) choices[0].selected = true
      return { kind: 'select', question, choices }
    }
  }
  const un = detectUnnumbered(lines)
  if (un) return un
  // y/n 兜底
  for (let i = lines.length - 1; i >= 0 && lines.length - i <= 12; i--) {
    const c = clean(lines[i])
    if (!c) continue
    if (/\((?:y\/n|yes\/no|y\/N|Y\/n)\)|\[y\/n\]/i.test(c)) return { kind: 'yesno', question: c, choices: [] }
    break // 只检查屏幕最后一条非空行，避免把历史说明文字里的 (y/n) 当作当前提示
  }
  return null
}

// A menu pushed into scrollback by subsequent output is no longer actionable.
const nearScreenEnd = (lines: string[], lastOption: number) =>
  lines.slice(lastOption + 1).filter(line => clean(line) !== '').length <= 12

// 无编号选择框：Claude 起手的「信任这个文件夹吗」就长这样——
//     ❯ No, exit
//       Yes, I trust this folder
//     Enter to confirm · Esc to cancel
// 一个编号都没有，OPT 那条路一项都认不出，于是新 worktree 的会话在对话面板里看着像
// 死了：既没消息也没提问框，人只能切回终端页去按键。
// 判据严到基本只有 TUI 满足：游标行 + 起始列严格对齐的兄弟行 + 附近的 Enter/Esc 操作提示。
function detectUnnumbered(lines: string[]): Prompt | null {
  const rows = lines.map(inner)
  for (let i = rows.length - 1; i >= 0; i--) {
    const m = rows[i].match(CURSOR_ONLY)
    if (!m || OPT.test(clean(rows[i]))) continue // 有编号的走上面那条正路
    const col = m[1].length + 1 + m[2].length    // 游标本身占一列
    // 兄弟选项：正文起始列与游标行**严格相同**，前面不能有别的字
    const sibling = (r: string): string | null => {
      if (r.length <= col || r[col] === ' ' || r.slice(0, col).trim() !== '') return null
      const label = r.slice(col).trim()
      return label && label.length <= 80 ? label : null
    }
    const group = [{ label: m[3].trim(), selected: true, idx: i }]
    for (let k = i - 1; k >= 0 && i - k <= 6; k--) {
      const l = sibling(rows[k]); if (!l) break
      group.unshift({ label: l, selected: false, idx: k })
    }
    for (let k = i + 1; k < rows.length && k - i <= 6; k++) {
      const l = sibling(rows[k]); if (!l) break
      group.push({ label: l, selected: false, idx: k })
    }
    if (group.length < 2) continue
    const top = group[0].idx
    const bottom = group[group.length - 1].idx
    const around = rows.slice(Math.max(0, top - 12), Math.min(rows.length, bottom + 4)).map((r) => r.trim()).join(' ')
    if (!nearScreenEnd(rows, bottom) || !ACTION_HINT.test(around)) continue
    // 真正在问的那句离选项挺远：信任框里隔着一整段权限清单，窄屏上还会折成四五行。
    // 所以按空行切成段、由近及远找带问号的那段（整段拼起来再判，问号常落在折行处），
    // 找不到就退回最近的那段。
    let question = ''
    let block: string[] = []
    const take = (b: string[]) => b.slice(-5).join(' ')
    for (let k = top - 1; k >= 0 && top - k <= 20; k--) {
      const c = clean(rows[k])
      if (c) { block.unshift(c); continue }
      if (!block.length) continue
      const text = take(block)
      if (!question) question = text
      if (QUESTION.test(text)) { question = text; break }
      block = []
    }
    if (block.length) {
      const text = take(block)
      if (!question || QUESTION.test(text)) question = text
    }
    return {
      kind: 'select',
      question,
      choices: group.map((o, n) => ({ num: n + 1, label: o.label, selected: o.selected })),
      numbered: false,
    }
  }
  return null
}

function PromptActions({ p, accent, busy, choose, press }: {
  p: Prompt
  accent: string
  busy: boolean
  choose: (target: Choice) => void
  press: (keys: string[]) => void
}) {
  const { t } = useI18n()
  return (
    <>
      {p.question && <div style={{ color: 'var(--text-bright)', fontSize: 13, marginBottom: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{p.question}</div>}
      {p.kind === 'select' ? (
        <Space direction="vertical" style={{ width: '100%' }} size={6}>
          {p.choices.map((ch) => (
            <Button key={ch.num} block disabled={busy} onClick={() => choose(ch)}
              style={{
                textAlign: 'left', height: 'auto', minHeight: 32, whiteSpace: 'normal', padding: '6px 10px',
                borderColor: ch.selected ? accent : 'var(--border)', color: 'var(--text-bright)',
                background: ch.selected ? accent + '22' : 'transparent',
              }}>
              <b style={{ color: accent, marginRight: 6, display: 'inline-flex', alignItems: 'center' }}>{ch.selected ? <ChevronRight size={12} /> : null}{p.numbered === false ? '' : `${ch.num}.`}</b>{ch.label}
            </Button>
          ))}
        </Space>
      ) : (
        <Space>
          <Button disabled={busy} onClick={() => press(['y'])} style={{ color: 'var(--ok)', borderColor: 'var(--ok-border)' }}>{t('prompt.yes')}</Button>
          <Button disabled={busy} onClick={() => press(['n'])} style={{ color: '#f85149', borderColor: '#f8514966' }}>{t('prompt.no')}</Button>
        </Space>
      )}
      <Space size={4} style={{ marginTop: 8 }}>
        <Button size="small" disabled={busy} onClick={() => press(['Up'])} title={t('prompt.up')} icon={<ArrowUp size={13} />} />
        <Button size="small" disabled={busy} onClick={() => press(['Down'])} title={t('prompt.down')} icon={<ArrowDown size={13} />} />
        <Button size="small" disabled={busy} onClick={() => press(['Enter'])}>{t('prompt.enter')}</Button>
        <Button size="small" disabled={busy} onClick={() => press(['Escape'])}>Esc</Button>
      </Space>
    </>
  )
}

function promptIdentity(prompt: Prompt | null) {
  return prompt ? JSON.stringify([prompt.kind, prompt.question, prompt.numbered, prompt.choices.map(choice => [choice.num, choice.label])]) : ''
}

const answering = new Set<string>()

function usePromptControl(name: string, enabled = true) {
  const active = usePageActive()
  const node = useCurrentNodeId()
  const key = JSON.stringify([node, name])
  const context = useMemo(() => ({ key, enabled: enabled && active }), [key, enabled, active])
  const scope = useRef<typeof context | null>(null)
  useLayoutEffect(() => {
    scope.current = context
    return () => { scope.current = null }
  }, [context])
  const { raw, fresh } = useSessionScreen(enabled ? name : null)
  const p = useMemo(() => detectPrompt(raw), [raw])
  const [busy, setBusy] = useState(false)

  const valid = () => scope.current === context && context.enabled && currentNodeId() === node && !document.hidden
  const read = async () => valid() ? detectPrompt(await readSessionScreen(name, node) || '') : null
  const keys = async (values: string[]) => {
    if (!valid()) return
    await api('POST', `/sessions/${encodeURIComponent(name)}/keys`, { keys: values })
  }
  const afterKeys = async () => {
    await new Promise(resolve => setTimeout(resolve, 350))
    return read()
  }

  const answer = async (send: (before: Prompt) => Promise<void>) => {
    if (!p || !fresh || !valid() || answering.has(key)) return
    answering.add(key)
    setBusy(true)
    try {
      const before = await read()
      if (before && promptIdentity(before) === promptIdentity(p)) await send(before)
    } catch (error) {
      console.error('failed to send prompt keys', error)
    } finally {
      answering.delete(key)
      setBusy(false)
    }
  }

  const press = (values: string[]) => answer(async () => {
    await keys(values)
    await afterKeys()
  })
  const choose = (target: Choice) => answer(async before => {
    if (before.numbered === false) {
      const from = before.choices.find(choice => choice.selected)?.num ?? 1
      const step = target.num - from
      if (step !== 0) {
        await keys(Array.from({ length: Math.abs(step) }, () => step > 0 ? 'Down' : 'Up'))
        const moved = await afterKeys()
        if (promptIdentity(moved) !== promptIdentity(before) || !moved?.choices.some(choice => choice.num === target.num && choice.selected)) return
      } else if (!before.choices.some(choice => choice.num === target.num && choice.selected)) {
        return
      }
    } else {
      await keys([String(target.num)])
      const remaining = await afterKeys()
      // Some agents accept the number immediately and move to the next question.
      if (promptIdentity(remaining) !== promptIdentity(before)) return
    }
    await keys(['Enter'])
    await afterKeys()
  })

  return { p: enabled && active ? p : null, busy: busy || !fresh, press, choose }
}

// 选择框面板：检测到 TUI 提示时显示在输入框上方，点击即注入按键完成选择
export function PromptPanel({ name, accent, enabled = true }: { name: string; accent: string; enabled?: boolean }) {
  const { p, busy, press, choose } = usePromptControl(name, enabled)
  const { t } = useI18n()

  if (!p) return null

  return (
    <div style={{ borderTop: `1px solid ${accent}55`, background: 'var(--bg-base)', padding: '10px 12px' }}>
      <div style={{ color: accent, fontSize: 12, fontWeight: 600, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5 }}><DotIcon size={9} />{t('prompt.confirmRequired')}</div>
      <PromptActions p={p} accent={accent} busy={busy} choose={choose} press={press} />
    </div>
  )
}

export function PromptDialog({ name, accent, enabled = true }: { name: string; accent: string; enabled?: boolean }) {
  const { p, busy, press, choose } = usePromptControl(name, enabled)
  const { t } = useI18n()
  const [dismissedKey, setDismissedKey] = useState<string | null>(null)
  const promptKey = p ? `${p.kind}:${p.question}:${p.choices.map((c) => `${c.num}:${c.label}`).join('|')}` : ''
  if (!enabled || !p || dismissedKey === promptKey) return null
  return (
    <Modal
      open
      title={<span style={{ color: accent }}>{t('prompt.confirmRequired')}</span>}
      footer={null}
      closable
      onCancel={() => setDismissedKey(promptKey)}
      mask={false}
      // 这是「浮在终端上的提示」，不是模态框：
      //   maskClosable=false —— 点别处不再算「取消」。默认 true 时 rc-dialog 见点击落在 wrap 上就
      //     onCancel，于是随手点一下终端这条提问就被 dismissedKey 记死、再也不弹（用户报的「点鼠标就没了」）。
      //   wrapper 透传 —— antd 的 .ant-modal-wrap 不论 mask 真假都是 fixed+inset:0 且可点，会把整页点击
      //     全吃掉（点不到底下的终端）。置 pointerEvents:none 让它透传；弹框本体 .ant-modal-content
      //     自带 pointer-events:auto，照常可点。关闭只走右上角 × 或答完题。
      maskClosable={false}
      width={520}
      centered
      styles={{ wrapper: { pointerEvents: 'none' }, header: { textAlign: 'center' }, body: { paddingTop: 12 } }}
    >
      <PromptActions p={p} accent={accent} busy={busy} choose={choose} press={press} />
    </Modal>
  )
}
