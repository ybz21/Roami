import { useI18n } from '../../i18n'

/** 会话内存画像（后端 ls --json 的 mem 字段）。limit=0 表示没设上限。 */
export type SessionMem = { cur: number; peak?: number; limit?: number; paused?: boolean; pauseReason?: string; warning?: boolean; pauseError?: boolean; relief?: { reclaimAt?: number; reclaimStatus?: string; reclaimed?: number; swapDelta?: number; compactAt?: number; compactStatus?: string } }

/** Warning and pause thresholds match the session memory policy. */
const WARN_AT = 60
const DANGER_AT = 80

export function memPercent(m?: SessionMem | null): number {
  if (!m || !m.limit || m.limit <= 0) return 0
  return Math.min(100, Math.round((m.cur / m.limit) * 100))
}

/** 超过警示线才值得在信息密度已经很高的地方占位置。 */
export function memNoteworthy(m?: SessionMem | null): boolean {
  return !!(m?.paused || m?.warning || m?.pauseError) || memPercent(m) >= WARN_AT
}

export function humanBytes(n: number): string {
  if (!n || n <= 0) return '—'
  if (n >= 1 << 30) return `${(n / (1 << 30)).toFixed(1)}G`
  if (n >= 1 << 20) return `${Math.round(n / (1 << 20))}M`
  return `${Math.round(n / 1024)}K`
}

/**
 * 会话内存条：平时是一条安静的细线，涨起来自己会跳出来。
 *
 * 这是 L3「预防」的那一半——L1 的上限管的是爆了之后损失可控，
 * 而在爆之前能看出是哪个会话在涨，靠的是这条线。
 * 见 docs/design/reliability/memory-guard.html §06。
 */
export function MemBar({ mem, compact }: { mem?: SessionMem | null; compact?: boolean }) {
  const { t } = useI18n()
  if (!mem || !mem.cur) return null
  const pct = memPercent(mem)
  const tone = pct >= DANGER_AT ? 'var(--danger)' : pct >= WARN_AT ? 'var(--warn)' : 'var(--ok)'
  const cur = humanBytes(mem.cur)
  const lim = mem.limit ? humanBytes(mem.limit) : ''
  const title = mem.limit
    ? t('session.mem.tip', { cur, limit: lim, pct: String(pct) })
    : t('session.mem.tipNoLimit', { cur })
  return (
    <span className="tt-membar" title={title} data-hot={pct >= DANGER_AT ? '1' : undefined}>
      {/* 没设上限就画不出「占了多少」，只报个数字，别画一条永远填不满的槽 */}
      {mem.limit ? (
        <i className="tr"><i className="fi" style={{ width: `${Math.max(pct, 2)}%`, background: tone }} /></i>
      ) : null}
      <b style={{ color: pct >= WARN_AT ? tone : undefined }}>{cur}</b>
      {mem.paused && <span>{t('session.mem.paused')}</span>}
      {/* 手机上分母是噪声：条本身已经表达了占比，数字留当前值就够 */}
      {!compact && lim && <span className="lim">/ {lim}</span>}
    </span>
  )
}
