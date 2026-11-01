import { isPrimaryShortcut, primaryShortcutLabel } from '../../../keyboard-platform'
// ⌘K 面板：全局搜索的门面。数据在 useSearchResults，行在 PaletteRow/PaletteList，
// 这里只剩「壳 + 键盘」。
//
// 从前它只是个「已打开的终端 + 页面名」的过滤器——面板里能搜到的东西，恰好是屏幕上
// 已经看得见的那些，等于什么也没搜。现在是三路结果的汇合处：
//
//   本地（0ms）   页面导航、已打开的会话；
//   后端（一跳）  项目、**全部**会话（不只开着的）、项目文件名，见 /search；
//   全文（显式）  文件内容，rg/grep，贵，所以要按一下才跑（⌘⏎ 或点底部那条）。
import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../../i18n'
import { ClockIcon, SearchIcon } from '../../../icons'
import { PaletteList } from './PaletteList'
import { useSearchResults } from './useSearchResults'
import type { PaletteActions, PaletteItem } from './types'

export function CommandPalette({ items, actions, dir, onClose }: {
  items: PaletteItem[]
  actions: PaletteActions
  /** 当前会话所在目录：让文件搜索在没进项目台账的目录里也有用 */
  dir?: string
  onClose: () => void
}) {
  const { t } = useI18n()
  const [q, setQ] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => { inputRef.current?.focus() }, [])

  const { rows, busy, contentBusy, truncated, indexing, runContentSearch } = useSearchResults(q, items, actions, dir)
  const needle = q.trim()

  useEffect(() => { setCursor(0) }, [q])
  useEffect(() => { if (cursor >= rows.length) setCursor(Math.max(0, rows.length - 1)) }, [rows.length, cursor])

  const runAt = (idx: number) => {
    const row = rows[idx]
    if (!row) return
    onClose()
    row.run()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, rows.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      if (isPrimaryShortcut(e)) runContentSearch() // ⌘⏎ = 去文件内容里找
      else runAt(cursor)
    } else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }

  return (
    <>
      <button aria-label={t('common.close')} onClick={onClose} style={{
        position: 'fixed', inset: 0, zIndex: 'var(--z-scrim)' as unknown as number,
        border: 0, padding: 0, background: 'rgba(1,4,9,.55)',
      }} />
      <div role="dialog" aria-modal="true" className="tt-palette">
        <div className="tt-palette-head">
          <SearchIcon size={16} />
          <input
            ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown}
            placeholder={t('workspace.searchPlaceholder')} aria-label={t('workspace.search')}
          />
          {busy && <i className="tt-palette-spin" aria-hidden />}
          <kbd>Esc</kbd>
        </div>

        <PaletteList rows={rows} cursor={cursor} busy={busy} truncated={truncated} indexing={indexing}
          onHover={setCursor} onRun={runAt} />

        <div className="tt-palette-foot">
          <button type="button" onClick={runContentSearch} disabled={!needle || contentBusy}>
            {contentBusy ? <ClockIcon size={13} /> : <SearchIcon size={13} />}
            {needle ? t('workspace.searchContentFor', { q: needle }) : t('workspace.searchContentHint')}
            <kbd>{modLabel()}⏎</kbd>
          </button>
          <span className="hint">↑↓ {t('workspace.hintMove')} · ⏎ {t('workspace.hintOpen')}</span>
        </div>
      </div>
    </>
  )
}

const modLabel = primaryShortcutLabel
