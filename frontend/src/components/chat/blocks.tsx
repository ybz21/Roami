// 对话渲染共用的小组件：代码框 / 折叠块 / 彩色 diff / 「正在生成」省略号。
import { useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { useI18n } from '../../i18n'
import { CheckIcon, Disclosure } from '../../icons'

export const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'

// 后端对「超长被截断」「图片块」只给哨兵，不写死中文（见 backend/api/claude.go 的 clip
// 与 rawContentText）；文案统一在这里出译文。转录正文与工具输出共用。
export function localizeSentinels(text: string, t: (key: string) => string): string {
  if (!text) return text
  return text
    .replace(/\n?…\[truncated\]$/, `\n${t('chat.truncated')}`)
    .replace(/^\[image\]$/gm, t('chat.imageBlock'))
}

// 时间戳 → HH:MM（解析失败返回空）
export function fmtTs(ts?: string): string {
  const locale = document.documentElement.lang || 'zh-CN'
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hour12: false })
}

// 跨 http（局域网非安全上下文）也能用的复制
export async function copyText(s: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(s); return true } catch {}
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = s; ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch { return false }
}

// text 始终用于复制；children(可选)是已高亮的节点，传入时渲染它而非纯文本。
// fill：整块预览面板里使用，代码框撑满父容器高度（去掉 maxHeight 上限）。
export function CodeBox({ text, max = 320, fill, className, children }: { text: string; max?: number; fill?: boolean; className?: string; children?: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const { t } = useI18n()
  const onCopy = (e: ReactMouseEvent) => { e.stopPropagation(); copyText(text); setCopied(true); setTimeout(() => setCopied(false), 1200) }
  return (
    <div style={{ position: 'relative', height: fill ? '100%' : undefined }} className="cc-codebox">
      <button onClick={onCopy} title={t('common.copy')} className="cc-copy"
        style={{ position: 'absolute', top: 6, right: 6, zIndex: 1, border: '1px solid var(--border)', background: 'var(--bg-container)', color: copied ? 'var(--ok)' : 'var(--text-dim)', borderRadius: 6, fontSize: 11, lineHeight: 1, padding: '3px 7px', cursor: 'pointer' }}>
        {copied ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><CheckIcon size={11} />{t('common.copied')}</span> : t('common.copy')}
      </button>
      <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: fill ? 0 : '6px 0 0', height: fill ? '100%' : undefined, maxHeight: fill ? 'none' : max, boxSizing: 'border-box', overflow: 'auto', background: 'var(--bg-base)', padding: 8, borderRadius: 6, fontFamily: MONO, fontSize: 12, lineHeight: 1.5, color: 'var(--text-bright)' }}>
        <code className={className}>{children ?? text}</code>
      </pre>
    </div>
  )
}

export function Collapsible({ label, text, color, open: dflt = false }: { label: string; text?: string; color: string; open?: boolean }) {
  const [open, setOpen] = useState(dflt)
  if (!text) return null
  return (
    <div style={{ fontSize: 12 }}>
      <a onClick={() => setOpen((o) => !o)} style={{ color, display: 'inline-flex', alignItems: 'center', gap: 4 }}><Disclosure open={open} />{label}</a>
      {open && <CodeBox text={text} />}
    </div>
  )
}

// 彩色 diff：+ 绿 / - 红 / @@,*** 紫。既能渲染补丁文本，也能渲染手动拼的 +/- 行。
export function Diff({ text, max = 360 }: { text: string; max?: number }) {
  const [copied, setCopied] = useState(false)
  const { t } = useI18n()
  const onCopy = (e: ReactMouseEvent) => {
    e.stopPropagation()
    copyText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1200)
  }
  return (
    <div style={{ position: 'relative' }} className="cc-codebox">
      <button onClick={onCopy} title={t('common.copy')} className="cc-copy"
        style={{ position: 'absolute', top: 6, right: 6, zIndex: 1, border: '1px solid var(--border)', background: 'var(--bg-container)', color: copied ? 'var(--ok)' : 'var(--text-dim)', borderRadius: 6, fontSize: 11, lineHeight: 1, padding: '3px 7px', cursor: 'pointer' }}>
        {copied ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><CheckIcon size={11} />{t('common.copied')}</span> : t('common.copy')}
      </button>
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: max, overflow: 'auto', fontFamily: MONO, fontSize: 12, lineHeight: 1.45, paddingRight: 54 }}>
        {text.split('\n').map((l, i) => {
          let color = 'var(--text-bright)'
          if (l.startsWith('+') && !l.startsWith('+++')) color = 'var(--ok)'
          else if (l.startsWith('-') && !l.startsWith('---')) color = '#f85149'
          else if (l.startsWith('@@') || l.startsWith('***')) color = '#d2a8ff'
          return <div key={i} style={{ color }}>{l || ' '}</div>
        })}
      </pre>
    </div>
  )
}

export function Typing({ color = 'var(--accent)' }: { color?: string }) {
  const { t } = useI18n()
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-start', margin: '6px 0' }}>
      <div style={{ background: 'var(--bg-container)', border: '1px solid var(--border)', borderRadius: 12, padding: '8px 14px', color: 'var(--text-dim)', fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        <span>{t('chat.generating')}</span>
        <span className="cc-dots" style={{ ['--cc-dot' as any]: color }}><i /><i /><i /></span>
      </div>
    </div>
  )
}
