// 会话状态条：输入框正上方一行 —— 模式 · 上下文 · 任务 · 失败 · 分支 · 用时 · 未读回底。
//
// 数据全都已经躺在转录里（见 15 设计 §11），搭 /transcript 现有轮询的车，不额外开端点。
// 条上只放**会变的**东西；模型名、推理档这类一整个会话都不动的收进详情，
// 常驻在条上只是占位置。
//
// 每一格都能点，而且点了要做**这一格自己那件事**——不是统一弹同一个面板：
//   模式 → 轮换权限模式（注入 Shift+Tab，跟在 TUI 里按是同一个动作）
//   上下文 → 详情（绝对值 / 模型 / 推理档）；快满了给「压缩」
//   任务 → 展开逐条进度
//   失败 → 跳到最近一次失败那条
//   分支 → 打开 Git 面板
//   用时 → 详情
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import { ArrowToBottom, ChecklistIcon, ChevronRight, ClockIcon, WarnIcon } from '../../icons'
import { BranchIcon } from '../git/parts'
import { CTX_FULL, CTX_TIGHT, MODE_COLOR, fmtElapsed, fmtTokens, modeKey, type AgentStatus } from './status'
import { TodoPane } from './tool-parts'

// 占用环。用 stroke-dasharray 画：16px 的图形上，一根描边比任何数字都快读。
function Ring({ percent, color, size = 16 }: { percent: number; color: string; size?: number }) {
  const r = 15
  const c = 2 * Math.PI * r
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" style={{ transform: 'rotate(-90deg)', flex: '0 0 auto' }} aria-hidden>
      <circle cx="18" cy="18" r={r} fill="none" stroke="var(--border)" strokeWidth="3.4" />
      <circle cx="18" cy="18" r={r} fill="none" stroke={color} strokeWidth="3.4" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0, Math.min(1, percent / 100)))} />
    </svg>
  )
}

function Chip({ onClick, title, tone, expanded, children }: {
  onClick?: () => void
  title?: string
  tone?: string
  expanded?: boolean
  children: React.ReactNode
}) {
  return (
    <button type="button" className={`cc-st-item${onClick ? ' is-btn' : ''}`} style={tone ? { color: tone } : undefined}
      aria-expanded={expanded} title={title} onClick={onClick} disabled={!onClick}>
      {children}
    </button>
  )
}

type Panel = 'none' | 'info' | 'tasks'

export type StatusActions = {
  /** 换模型：发 /model，Claude Code 自己弹选择框（PromptPanel 接住） */
  onPickModel?: () => void
  /** 跳到最近一次失败的工具调用 */
  onJumpError?: () => void
  /** 打开 Git 面板 */
  onOpenGit?: () => void
  /** 让 Agent 压缩上下文（发 /compact） */
  onCompact?: () => void
}

export function StatusBar({ status, accent, unread, onJump, actions = {} }: {
  status: AgentStatus
  accent: string
  unread: number
  onJump?: () => void
  actions?: StatusActions
}) {
  const { t } = useI18n()
  const [panel, setPanel] = useState<Panel>('none')
  const toggle = (p: Panel) => setPanel((cur) => (cur === p ? 'none' : p))

  // 手机上七八个 chip 一行放不下 → 横滑。两侧渐隐提示「这边还有」，
  // 沿用快捷键条那套 data-l/data-r 约定（见 .tt-keyrow），不另发明一套。
  const stripRef = useRef<HTMLDivElement>(null)
  const [fade, setFade] = useState({ l: false, r: false })
  const syncFade = useCallback(() => {
    const el = stripRef.current
    if (!el) return
    setFade({ l: el.scrollLeft > 2, r: el.scrollLeft + el.clientWidth < el.scrollWidth - 2 })
  }, [])
  useEffect(() => {
    const el = stripRef.current
    if (!el) return
    syncFade()
    // chip 数量会随会话变（多出一个「失败」就可能从放得下变成放不下），用 RO 而不是只在挂载时量一次
    const ro = new ResizeObserver(syncFade)
    ro.observe(el)
    for (const c of Array.from(el.children)) ro.observe(c)
    return () => ro.disconnect()
  }, [syncFade, status])

  const ctx = status.context
  // 上下文接近满了要变色：85% 起黄，95% 起红。这是唯一会「越用越糟」的指标。
  const tight = !!ctx && ctx.percent >= CTX_TIGHT
  const ctxColor = !ctx ? accent : ctx.percent >= CTX_FULL ? 'var(--danger)' : tight ? 'var(--warn)' : accent
  const quotaColor = status.quota != null && status.quota >= CTX_FULL ? 'var(--danger)'
    : status.quota != null && status.quota >= CTX_TIGHT ? 'var(--warn)' : accent
  const hasAny = status.mode || ctx || status.tasks || status.quota || status.branch || status.errors || unread > 0
  if (!hasAny) return null

  const modeLabel = status.mode ? t(modeKey(status.mode.id)) : ''
  // 认不出的模式 id 直接显示原文：新模式先出现在 CLI 里是常态，不该显示成 key
  const modeText = modeLabel.startsWith('chat.mode.') ? status.mode!.id : modeLabel
  // 小数位只在 10% 以下给一位：两位数还带小数会一直跳，看不出真的在涨
  const pct = ctx ? ctx.percent.toFixed(ctx.percent < 10 ? 1 : 0) : ''

  return (
    <div className="cc-statusbar">
      <div className="cc-st-scroll" ref={stripRef} onScroll={syncFade}
        data-l={fade.l ? '' : undefined} data-r={fade.r ? '' : undefined}>
        {/* 条头是模型名，点了换模型；权限模式（auto / plan …）只在信息面板里列——
            条上一枚写着「auto」的 pill 没人看得懂是什么的 auto */}
        {(status.model || actions.onPickModel) && (
          <button type="button" className={`cc-st-pill${actions.onPickModel ? ' is-btn' : ''}`}
            style={status.mode ? { color: MODE_COLOR[status.mode.tone] } : undefined} disabled={!actions.onPickModel}
            onClick={actions.onPickModel} title={actions.onPickModel ? t('chat.modelPick') : t('chat.model')}>
            {status.mode && <i style={{ background: MODE_COLOR[status.mode.tone] }} />}{status.model || t('chat.model')}
          </button>
        )}

        {ctx && (
          <Chip onClick={() => toggle('info')} expanded={panel === 'info'}
            title={`${fmtTokens(ctx.used)} / ${fmtTokens(ctx.window)}`}>
            <Ring percent={ctx.percent} color={ctxColor} />
            <span>{t('chat.contextUsed')}</span>
            <span style={{ color: ctxColor, fontVariantNumeric: 'tabular-nums' }}>{pct}%</span>
          </Chip>
        )}

        {status.quota != null && (
          <Chip title={t('chat.quotaTitle')}>
            <Ring percent={status.quota} color={quotaColor} />
            <span>{t('chat.quotaTitle')}</span>
            <span style={{ color: quotaColor, fontVariantNumeric: 'tabular-nums' }}>{Math.round(status.quota)}%</span>
          </Chip>
        )}

        {status.tasks && (
          <Chip onClick={() => toggle('tasks')} expanded={panel === 'tasks'} title={status.tasks.doing || t('chat.taskPanel')}>
            <ChecklistIcon size={13} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{status.tasks.done}/{status.tasks.total}</span>
            <span className="cc-st-chev" style={{ transform: panel === 'tasks' ? 'rotate(-90deg)' : 'rotate(90deg)' }}>
              <ChevronRight size={11} />
            </span>
          </Chip>
        )}

        {/* 失败数：整条里唯一的红。点了跳到最近一次——「哪儿挂了」是看到这个数字后的下一个问题 */}
        {!!status.errors && (
          <Chip onClick={actions.onJumpError} tone="var(--danger)" title={t('chat.errorsTitle', { count: status.errors })}>
            <WarnIcon size={12} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{status.errors}</span>
          </Chip>
        )}

        {status.branch && (
          <Chip onClick={actions.onOpenGit} title={status.cwd || status.branch}>
            <BranchIcon size={12} />
            <span className="cc-st-ellip">{status.branch}</span>
          </Chip>
        )}

        {status.elapsed != null && (
          <Chip onClick={() => toggle('info')} expanded={panel === 'info'} title={t('chat.elapsedTitle')}>
            <ClockIcon size={12} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtElapsed(status.elapsed)}</span>
          </Chip>
        )}

      </div>

      {/* 「回到底部」钉在滚动条带**外面**——它是动作，不能被横滑滑走。
          它原本是右下角的悬浮圆钮，跟这里重复；合并后少一个浮层，顺带带上未读数：
          上滚离底之后「新消息有多少」是这条唯一能回答的问题。 */}
      {unread > 0 && (
        <button type="button" className="cc-st-jump" style={{ background: accent }} onClick={onJump} title={t('chat.jumpToBottom')}>
          <ArrowToBottom size={13} />
          <b>{unread > 99 ? '99+' : unread}</b>
        </button>
      )}

      {/* 任务展开：逐条列出来看进度。复用工具渲染里那套待办件，
          状态点是画的不是字符，跟对话里的 TodoWrite 长一个样。 */}
      {panel === 'tasks' && status.tasks && (
        <div className="cc-st-panel">
          <TodoPane items={status.tasks.list.map((x) => ({ id: x.id, content: x.subject, status: x.status }))} />
        </div>
      )}

      {panel === 'info' && (
        <div className="cc-st-panel is-info">
          {status.model && <div><span>{t('chat.model')}</span><b>{status.model}</b></div>}
          {status.effort && <div><span>{t('chat.effort')}</span><b>{status.effort}</b></div>}
          {ctx && <div><span>{t('chat.context')}</span><b>{fmtTokens(ctx.used)} / {fmtTokens(ctx.window)}</b></div>}
          {status.mode && <div><span>{t('chat.modeLabel')}</span><b>{modeText}</b></div>}
          {status.elapsed != null && <div><span>{t('chat.elapsed')}</span><b>{fmtElapsed(status.elapsed)}</b></div>}
          {status.cwd && <div><span>{t('chat.cwd')}</span><b>{status.cwd}</b></div>}
          {/* 快满了才给「压缩」：平时摆在那儿是个误触源，它会真的往会话里发一条命令 */}
          {tight && actions.onCompact && (
            <button type="button" className="cc-st-act" onClick={() => { setPanel('none'); actions.onCompact!() }}>
              {t('chat.compact')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
