// 一条消息的渲染。Claude 与 Codex 共用这一份——此前两边各写一份近乎重复的气泡，
// 结果同一个「思考」在两页长得不一样。差异收敛成一个 side 参数（强调色 + 思考/推理的叫法）。
//
// 排版要点：助手消息按「正文段 / 工具段」分开——正文进气泡，**工具段平铺全宽不套气泡**。
// 工具本来就不是「说的话」，塞进气泡里等于给每次 Read 描一道框，一屏十几次就全是框。
import { memo, type ReactNode } from 'react'
import Markdown from '../markdown/Markdown'
import { Collapsible, copyText, fmtTs, localizeSentinels, MONO } from './blocks'
import { useI18n } from '../../i18n'
import type { Block, Msg } from './types'
import { LooseResult, ToolView } from './tool-render'
import { TerminalIcon } from '../../icons'
import { splitAtPaths } from '../../agent-paths'
import { noticePrefixOf } from '../shell/session-drop'
import { IMG_EXT } from '../files/file-utils'
import { MentionedImage } from './MentionedImage'

export const CODEX_ACCENT = 'var(--accent)'

export type Side = 'claude' | 'codex'

// 后端对 redacted_thinking 只能给个占位；文案在前端出，后端不写死中文（见 backend/api/claude.go）
const REDACTED_THINKING = '[redacted_thinking]'

const isToolBlock = (b: Block) => b.kind === 'tool_use' || b.kind === 'tool_result'

// 把连续的同类块并成段：正文段进气泡，工具段平铺。
function segments(blocks: Block[]): { tool: boolean; blocks: Block[] }[] {
  const out: { tool: boolean; blocks: Block[] }[] = []
  for (const b of blocks) {
    const tool = isToolBlock(b)
    const last = out[out.length - 1]
    if (last && last.tool === tool) last.blocks.push(b)
    else out.push({ tool, blocks: [b] })
  }
  return out
}

// 用户消息里混着 Claude Code 自己塞的标记块：斜杠命令、命令回显、系统提醒。
// 原样打出来就是一坨 XML；拆开之后正文才是正文。
type UserText = { command: string; args: string; stdout: string[]; reminders: string[]; body: string }

export function parseUserText(raw: string): UserText {
  let command = ''
  let args = ''
  const stdout: string[] = []
  const reminders: string[] = []
  let body = String(raw)
    .replace(/<command-name>([\s\S]*?)<\/command-name>/g, (_, v) => { command = String(v).trim(); return '' })
    .replace(/<command-args>([\s\S]*?)<\/command-args>/g, (_, v) => { args = String(v).trim(); return '' })
    .replace(/<command-message>[\s\S]*?<\/command-message>/g, '')
    .replace(/<local-command-stdout>([\s\S]*?)<\/local-command-stdout>/g, (_, v) => { const s = String(v).trim(); if (s) stdout.push(s); return '' })
    .replace(/<system-reminder>([\s\S]*?)<\/system-reminder>/g, (_, v) => { const s = String(v).trim(); if (s) reminders.push(s); return '' })
  body = body.trim()
  return { command, args, stdout, reminders, body }
}

function messageText(m: Msg): string {
  return m.blocks.map((b) => (b.kind === 'tool_use' ? b.input || '' : b.text || '')).filter(Boolean).join('\n\n')
}

// 消息尾巴：时间 + 复制。工具段不给尾巴——那不是「谁说的话」。
function Footer({ m, align }: { m: Msg; align: 'flex-start' | 'flex-end' }) {
  const { t } = useI18n()
  return (
    <span style={{ display: 'inline-flex', alignSelf: align, alignItems: 'center', gap: 'var(--sp-2)', fontSize: 'var(--fs-micro)', color: 'var(--text-dimmer)', padding: '0 var(--sp-1)' }}>
      {m.ts && fmtTs(m.ts)}
      <button className="cc-msg-copy" onClick={() => copyText(messageText(m))}>{t('common.copy')}</button>
    </span>
  )
}

function Prose({ blocks, accent, side }: { blocks: Block[]; accent: string; side: Side }) {
  const { t } = useI18n()
  const thinkLabel = side === 'codex' ? t('chat.reasoning') : t('chat.thinking')
  return (
    <>
      {blocks.map((b, i) => {
        if (b.kind === 'thinking') {
          const text = b.text === REDACTED_THINKING ? t('chat.thinkingRedacted') : localizeSentinels(b.text || '', t)
          return <Collapsible key={i} label={thinkLabel} text={text} color="var(--text-dim)" />
        }
        return <Markdown key={i} accent={accent}>{localizeSentinels(b.text || '', t)}</Markdown>
      })}
    </>
  )
}

// 用户气泡：右侧实心块。命令小标、命令回显、系统提醒都挪到气泡外，
// 免得白字压在实心底色上再套一层折叠框。
const isImagePath = (p: string) => IMG_EXT.includes((p.split('.').pop() || '').toLowerCase())

/**
 * 正文里被 @ 引用的图片就地换成缩略图卡片，其余文字照常走 Markdown。
 *
 * 就地替换而不是「正文照旧、图片另起一排」：路径常常嵌在句子里（「看看 @/tmp/a.png
 * 这个问题」），把它抽到底下，句子就断在半空；而留在原地又等于把同一件事说两遍。
 */
function BodyWithImages({ text, accent }: { text: string; accent: string }) {
  const segs = splitAtPaths(text, isImagePath)
  if (segs.length === 1 && segs[0].kind === 'text') return <Markdown accent={accent}>{text}</Markdown>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)', alignItems: 'flex-start' }}>
      {segs.map((sg, i) => (sg.kind === 'path'
        ? <MentionedImage key={i} path={sg.path} onAccent={accent === '#fff'} />
        : <Markdown key={i} accent={accent}>{sg.text}</Markdown>))}
    </div>
  )
}

/** 整条消息就是 Roami 的注入：第一个文本块以标记开头（改名前的 `[Roam]` 也认） */
function isRoamNotice(m: Msg): boolean {
  const first = m.blocks.find((b) => b.kind === 'text')
  return noticePrefixOf(first?.text) !== null
}

function RoamNotice({ m }: { m: Msg }) {
  const { t } = useI18n()
  const text = m.blocks.filter((b) => b.kind === 'text').map((b) => b.text || '').join('\n')
  const prefix = noticePrefixOf(text) || ''
  // 默认收起：它是给 Agent 看的上下文，人只要知道「这儿发生过一次注入」就够了
  return (
    <div className="cc-msg" data-msg-id={m.id} style={{ margin: 'var(--sp-1) 0' }}>
      <Collapsible label={t('chat.roamNotice')} text={prefix ? text.replace(prefix, '') : text} color="var(--text-dimmer)" />
    </div>
  )
}

function UserMessage({ m, accent }: { m: Msg; accent: string }) {
  const { t } = useI18n()
  const parsed = m.blocks.map((b) => (b.kind === 'text' ? parseUserText(b.text || '') : null))
  const extras = parsed.filter(Boolean) as UserText[]
  const stdout = extras.flatMap((p) => p.stdout)
  const reminders = extras.flatMap((p) => p.reminders)
  const hasBubble = m.blocks.some((b, i) => (parsed[i] ? !!(parsed[i]!.body || parsed[i]!.command) : !!b.text))
  return (
    <div className="cc-msg" data-msg-id={m.id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', margin: 'var(--sp-1) 0', gap: 2 }}>
      {hasBubble && (
        <div style={{ maxWidth: '86%', background: accent, borderRadius: 'var(--r-card)', padding: 'var(--sp-2) var(--sp-3)', color: '#fff', display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)' }}>
          {m.blocks.map((b, i) => {
            const p = parsed[i]
            // 实心底上正文是白字，链接跟着走白色——默认那支蓝压在蓝底上根本看不见
            if (!p) return b.text ? <BodyWithImages key={i} text={b.text} accent="#fff" /> : null
            return (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)' }}>
                {p.command && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--sp-1)', fontFamily: MONO, fontSize: 'var(--fs-meta)', opacity: .9 }}>
                    <TerminalIcon size={12} />{p.command}{p.args ? ` ${p.args}` : ''}
                  </span>
                )}
                {p.body && <BodyWithImages text={p.body} accent="#fff" />}
              </div>
            )
          })}
        </div>
      )}
      {stdout.map((sOut, i) => <Collapsible key={`o${i}`} label={t('chat.commandOutput')} text={sOut} color="var(--text-dim)" />)}
      {reminders.map((r, i) => <Collapsible key={`r${i}`} label={t('chat.systemReminder')} text={r} color="var(--text-dimmer)" />)}
      <Footer m={m} align="flex-end" />
    </div>
  )
}

export const ChatMessage = memo(function ChatMessage({ m, results, side }: { m: Msg; results: Record<string, Block>; side: Side }) {
  const accent = 'var(--accent)'
  const solid = 'var(--accent-solid)'

  // Roam 自己塞进去的那段话（如「旁边还有一个会话」的介绍词）：它是经
  // SendPromptSubmit 投进输入框并回车的，转录里就记成一个 user turn——可它不是
  // 你说的话，画成实心蓝气泡会把对话搅浑。收成一条可展开的通知。
  if (m.role === 'user' && isRoamNotice(m)) return <RoamNotice m={m} />
  if (m.role === 'user') return <UserMessage m={m} accent={solid} />

  const segs = segments(m.blocks)
  const hasProse = segs.some((sg) => !sg.tool)
  return (
    <div className="cc-msg" data-msg-id={m.id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'stretch', margin: 'var(--sp-1) 0', gap: 'var(--sp-1)' }}>
      {segs.map((sg, i) => (sg.tool ? (
        <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {sg.blocks.map((b, j): ReactNode => (
            b.kind === 'tool_use'
              ? <ToolView key={j} block={b} result={b.id ? results[b.id] : undefined} />
              : <LooseResult key={j} block={b} />
          ))}
        </div>
      ) : (
        <div key={i} style={{ background: 'var(--bg-container)', border: '1px solid var(--border)', borderRadius: 'var(--r-card)', padding: 'var(--sp-2) var(--sp-3)', color: 'var(--text-bright)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)' }}>
          <Prose blocks={sg.blocks} accent={accent} side={side} />
        </div>
      )))}
      {hasProse && <Footer m={m} align="flex-start" />}
    </div>
  )
})
