import { usePageEffect } from '../../page-activity'
// 危险操作目标可视化 / 就地确认：关闭 pane 之前，把要关的那个窗格用聚光灯效果套出来，
// 确认卡直接锚定在它旁边，而不是像 tmux 原生 confirm-before 那样在终端最底部弹一行
// 写着不透明编号的文字。见 docs/roam-product-audit-2026-07-30.html P0「危险操作目标可视化」。
import type { CSSProperties } from 'react'
import { Button } from 'antd'
import { useI18n } from '../../i18n'
import { MONO } from '../chat/blocks'

export interface PaneCloseTarget {
  session: string
  paneId: string
  cwd: string
  cmd: string
  panesInWindow: number
  rect: { x: number; y: number; width: number; height: number }
}

export function PaneCloseConfirm({ target, busy, error, onConfirm, onCancel }: {
  target: PaneCloseTarget
  busy: boolean
  error?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const { rect } = target

  // Y/N 快捷键：审计 mockup 明确要求「操作按钮为『关闭此窗格 / 取消』，同时保留 Y / N 快捷键」
  usePageEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (busy) return
      if (e.key === 'y' || e.key === 'Y') onConfirm()
      else if (e.key === 'n' || e.key === 'N' || e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onConfirm, onCancel])

  const cardWidth = 320
  const below = rect.y + rect.height + 8
  const flip = below + 168 > window.innerHeight
  const cardStyle: CSSProperties = {
    position: 'fixed',
    left: Math.max(8, Math.min(rect.x, window.innerWidth - cardWidth - 8)),
    top: flip ? Math.max(8, rect.y - 168) : below,
    width: cardWidth,
    zIndex: 1001,
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border)',
    borderRadius: 10,
    padding: 14,
    boxShadow: 'var(--elevated-shadow)',
  }

  return (
    <>
      {/* 聚光灯：矩形本身透明，四周整页压暗，眼睛第一时间落在要关的那个窗格上 */}
      <div aria-hidden style={{
        position: 'fixed', left: rect.x, top: rect.y, width: rect.width, height: rect.height,
        zIndex: 1000, pointerEvents: 'none', borderRadius: 6,
        boxShadow: '0 0 0 9999px rgba(0,0,0,.45), 0 0 0 2px #f85149',
      }} />
      <div style={cardStyle} role="alertdialog" aria-label={t('pane.close.title')}>
        <div style={{ fontWeight: 700, color: 'var(--text-bright)', marginBottom: 6 }}>{t('pane.close.title')}</div>
        <div style={{
          fontSize: 12, color: 'var(--text-dim)', fontFamily: MONO,
          marginBottom: 6, wordBreak: 'break-all',
        }}>
          {target.session} · {target.cwd}{target.cmd ? ` · ${target.cmd}` : ''}
        </div>
        <div style={{ fontSize: 12, color: target.panesInWindow <= 1 ? '#f5a623' : 'var(--text-dim)', marginBottom: 10 }}>
          {target.panesInWindow <= 1 ? t('pane.close.lastPane') : t('pane.close.impact')}
        </div>
        {error && <div style={{ fontSize: 12, color: '#f85149', marginBottom: 8 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button size="small" disabled={busy} onClick={onCancel}>{t('pane.close.cancel')}</Button>
          <Button size="small" danger type="primary" loading={busy} onClick={onConfirm}>{t('pane.close.confirm')}</Button>
        </div>
      </div>
    </>
  )
}
