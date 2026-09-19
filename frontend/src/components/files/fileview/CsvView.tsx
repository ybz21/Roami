// CSV / TSV 展示：解析成表格（截前 80 行 × 12 列，见 parseDelimited）。
import { type CSSProperties } from 'react'
import { useRememberedScroll } from './view-state-memory'
import { parseDelimited } from '../file-utils'
import { PreviewShell } from './PreviewShell'
import { useI18n } from '../../../i18n'

function cellStyle(head: boolean): CSSProperties {
  return {
    padding: '6px 8px', border: '1px solid var(--border-subtle)', textAlign: 'left',
    background: head ? 'var(--bg-container)' : 'transparent', color: head ? 'var(--text-bright)' : 'var(--text-dim)',
    maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  }
}

export function CsvView({ path, text, sep, height, inline, truncated }: {
  path: string
  text: string
  sep: ',' | '\t'
  height: string
  inline?: boolean
  truncated?: boolean
}) {
  const { t } = useI18n()
  const scroll = useRememberedScroll('csv:' + path)
  const rows = parseDelimited(text, sep)
  const head = rows[0] || []
  const body = rows.slice(1)
  return (
    <PreviewShell path={path} title={t('file.tablePreviewTitle', { kind: sep === ',' ? 'CSV' : 'TSV' })} inline={inline} truncated={truncated}>
      <div ref={scroll.ref} onScroll={scroll.onScroll} style={{ height, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>{head.length > 0 && <tr>{head.map((c, i) => <th key={i} style={cellStyle(true)}>{c || t('file.column', { index: i + 1 })}</th>)}</tr>}</thead>
          <tbody>{body.map((r, i) => <tr key={i}>{head.map((_, j) => <td key={j} style={cellStyle(false)}>{r[j] || ''}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </PreviewShell>
  )
}
