// 交互式选择框检测与响应 —— 供 ClaudeChat / CodexChat 专业渲染模式复用。
//
// 背景：Claude/Codex 的权限确认、选项菜单是终端 TUI 实时状态，不在 JSONL transcript 里，
// 所以对话面板渲染不出、也无从响应。这里从实时屏幕(capture，纯文本含 ❯/框线)解析出
// 选择框，渲染成可点按钮；点击经 POST /sessions/:name/keys 注入原始按键完成选择。
import { useEffect, useState } from 'react'
import { Button, Modal, Space } from 'antd'
import { api } from '../api'
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
  if (sequential) {
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
    if (!ACTION_HINT.test(around)) continue
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

// 后台标签的待确认状态需要连续采样后才切换。终端 TUI 在重绘中途可能短暂形成
// “编号列表 + 游标”的残帧；单次采样不能让标签立刻增删“待确认”并造成视觉闪动。
export interface PromptSignal { candidate: boolean; streak: number; stable: boolean }
export function advancePromptSignal(previous: PromptSignal | undefined, candidate: boolean, confirmations = 2): PromptSignal {
  const sameCandidate = previous?.candidate === candidate
  const streak = sameCandidate ? (previous?.streak || 0) + 1 : 1
  const stable = streak >= confirmations ? candidate : (previous?.stable || false)
  return { candidate, streak, stable }
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

function usePromptControl(name: string) {
  const [p, setP] = useState<Prompt | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!name) { setP(null); return }
    let stop = false
    const poll = async () => { const r = await fetchPrompt(name); if (!stop) setP(r) }
    poll()
    const t = setInterval(poll, 1200)
    return () => { stop = true; clearInterval(t) }
  }, [name])

  const press = async (keys: string[]) => {
    setBusy(true)
    try {
      await api('POST', `/sessions/${encodeURIComponent(name)}/keys`, { keys })
      setTimeout(async () => { setP(await fetchPrompt(name)) }, 350)
    } catch (err) {
      console.error('failed to send prompt keys', err)
    } finally {
      setBusy(false)
    }
  }

  // 无编号选择框只能用方向键：先把游标挪到目标上，**确认它真的挪到了**再回车。
  // 不核对就回车的代价是替用户答错——信任框的第一项正是「No, exit」，按错一格会话就没了。
  const chooseByArrows = async (before: Prompt, target: Choice) => {
    const from = before.choices.find((c) => c.selected)?.num ?? 1
    const step = target.num - from
    if (step !== 0) {
      const keys = Array.from({ length: Math.abs(step) }, () => (step > 0 ? 'Down' : 'Up'))
      await api('POST', `/sessions/${encodeURIComponent(name)}/keys`, { keys })
      await new Promise((r) => setTimeout(r, 350))
    }
    const moved = await fetchPrompt(name)
    // 同名选项也要认得出，所以位置和文本都对上才算挪到了
    const landed = moved?.numbered === false && moved.choices.length === before.choices.length &&
      moved.choices.find((c) => c.selected)?.num === target.num && moved.choices[target.num - 1]?.label === target.label
    if (!landed) { setP(moved); return }
    await api('POST', `/sessions/${encodeURIComponent(name)}/keys`, { keys: ['Enter'] })
    setTimeout(async () => { setP(await fetchPrompt(name)) }, 350)
  }

  // 点选项只发数字，350ms 后再看屏幕：同一个问题还在（数字只是挪了高亮）才补 Enter。
  // 以前一律发「数字 + Enter」：Claude Code 的 AskUserQuestion 按数字就直接进下一题，
  // 那个 Enter 落到下一题上，把它的第一个选项当成你的答案交了；多问一题就多错一题。
  const choose = async (target: Choice) => {
    const before = p
    setBusy(true)
    try {
      if (before?.numbered === false) { await chooseByArrows(before, target); return }
      await api('POST', `/sessions/${encodeURIComponent(name)}/keys`, { keys: [String(target.num)] })
      await new Promise((r) => setTimeout(r, 350))
      const after = await fetchPrompt(name)
      if (after && before && after.kind === 'select' && before.kind === 'select' && after.question === before.question) {
        await api('POST', `/sessions/${encodeURIComponent(name)}/keys`, { keys: ['Enter'] })
        setTimeout(async () => { setP(await fetchPrompt(name)) }, 350)
      } else {
        setP(after)
      }
    } catch (err) {
      console.error('failed to send prompt keys', err)
    } finally {
      setBusy(false)
    }
  }

  return { p, busy, press, choose }
}

async function fetchPrompt(name: string): Promise<Prompt | null> {
  try {
    const r = await api('GET', `/sessions/${encodeURIComponent(name)}/capture?lines=50`)
    return detectPrompt(r.data || '')
  } catch { return null }
}

// 选择框面板：检测到 TUI 提示时显示在输入框上方，点击即注入按键完成选择
export function PromptPanel({ name, accent }: { name: string; accent: string }) {
  const { p, busy, press, choose } = usePromptControl(name)
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
  const { p, busy, press, choose } = usePromptControl(enabled ? name : '')
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
