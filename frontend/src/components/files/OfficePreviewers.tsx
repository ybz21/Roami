import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Spin } from 'antd'
import { renderAsync } from 'docx-preview'
import * as XLSX from 'xlsx-js-style'
import { useI18n } from '../../i18n'

interface CommonProps {
  src: string
  name: string
  downloadUrl: string
}

export function DocxFilePreview({ src, name, downloadUrl }: CommonProps) {
  const { t } = useI18n()
  const hostRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    const host = hostRef.current
    if (!host) return
    host.innerHTML = ''
    setLoading(true)
    setError('')

    async function load() {
      try {
        const res = await fetch(src)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const blob = await res.blob()
        if (cancelled || !hostRef.current) return
        hostRef.current.innerHTML = ''
        await renderAsync(blob, hostRef.current, undefined, {
          className: 'docx-wrapper',
          inWrapper: false,
          ignoreWidth: false,
          ignoreHeight: false,
          ignoreFonts: false,
          breakPages: true,
          ignoreLastRenderedPageBreak: true,
          trimXmlDeclaration: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
        })
        if (!cancelled) setLoading(false)
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message || t('office.docxFailed'))
          setLoading(false)
        }
      }
    }

    load()
    return () => {
      cancelled = true
      if (host) host.innerHTML = ''
    }
  }, [src])

  if (error) return <PreviewError title={t('office.docxFailed')} detail={error} name={name} downloadUrl={downloadUrl} />
  return (
    <div style={{ height: '100%', overflow: 'auto', background: '#eef1f5' }}>
      {loading && <Loading />}
      <div ref={hostRef} style={{ minHeight: loading ? 220 : undefined, padding: 18 }} />
    </div>
  )
}

interface CellStyle {
  backgroundColor?: string
  color?: string
  fontWeight?: string
  fontStyle?: string
  textDecoration?: string
  textAlign?: string
  verticalAlign?: string
  borderTop?: string
  borderRight?: string
  borderBottom?: string
  borderLeft?: string
}

interface CellData {
  value: string
  rowSpan: number
  colSpan: number
  style: CellStyle
  hidden?: boolean
}

interface SheetData {
  name: string
  cells: CellData[][]
  colWidths: number[]
}

const DEFAULT_COLUMN_WIDTH_PX = 8.43 * 7
const CELL_DEFAULT_BORDER = '1px solid #d0d7de'

function parseExcelFile(arrayBuffer: ArrayBuffer): SheetData[] {
  const workbook = XLSX.read(arrayBuffer, { type: 'array', cellStyles: true })
  const sheetsData: SheetData[] = []

  for (const sheetName of workbook.SheetNames) {
    const worksheet = workbook.Sheets[sheetName]
    if (!worksheet) continue
    const range = XLSX.utils.decode_range(worksheet['!ref'] || 'A1')
    const colCount = range.e.c - range.s.c + 1
    const rowCount = range.e.r - range.s.r + 1
    const colWidths: number[] = []
    const cols = worksheet['!cols'] || []

    for (let c = 0; c < colCount; c++) {
      const colInfo = cols[c] as { wpx?: number; width?: number } | undefined
      colWidths.push(((colInfo?.wpx || colInfo?.width || 8.43) * 7) || DEFAULT_COLUMN_WIDTH_PX)
    }

    const mergeMap = new Map<string, { rowSpan: number; colSpan: number; isMaster: boolean }>()
    for (const merge of worksheet['!merges'] || []) {
      const startRow = merge.s.r + 1
      const startCol = merge.s.c + 1
      const endRow = merge.e.r + 1
      const endCol = merge.e.c + 1
      mergeMap.set(`${startRow}-${startCol}`, { rowSpan: endRow - startRow + 1, colSpan: endCol - startCol + 1, isMaster: true })
      for (let r = startRow; r <= endRow; r++) {
        for (let c = startCol; c <= endCol; c++) {
          if (r !== startRow || c !== startCol) mergeMap.set(`${r}-${c}`, { rowSpan: 1, colSpan: 1, isMaster: false })
        }
      }
    }

    const cells: CellData[][] = []
    for (let r = 0; r < rowCount; r++) {
      const row: CellData[] = []
      for (let c = 0; c < colCount; c++) {
        const mergeInfo = mergeMap.get(`${r + 1}-${c + 1}`)
        if (mergeInfo && !mergeInfo.isMaster) {
          row.push({ value: '', rowSpan: 1, colSpan: 1, style: {}, hidden: true })
          continue
        }
        const cell = worksheet[XLSX.utils.encode_cell({ r, c })] as XLSX.CellObject | undefined
        const style = ((cell as any)?.s || {}) as any
        const backgroundColor = style.fgColor?.rgb ? `#${style.fgColor.rgb}` : style.bgColor?.rgb ? `#${style.bgColor.rgb}` : style.fill?.fgColor?.rgb ? `#${style.fill.fgColor.rgb}` : undefined
        const border = (b: any) => b?.style ? `${b.style === 'thick' ? 3 : b.style === 'medium' ? 2 : 1}px ${b.style === 'dotted' ? 'dotted' : b.style === 'dashed' ? 'dashed' : 'solid'} ${b.color?.rgb ? `#${b.color.rgb}` : '#000'}` : undefined
        row.push({
          value: cell?.w !== undefined ? String(cell.w) : cell?.v !== undefined ? String(cell.v) : '',
          rowSpan: mergeInfo?.rowSpan ?? 1,
          colSpan: mergeInfo?.colSpan ?? 1,
          style: {
            backgroundColor,
            color: style.font?.color?.rgb ? `#${style.font.color.rgb}` : undefined,
            fontWeight: style.font?.bold ? 'bold' : undefined,
            fontStyle: style.font?.italic ? 'italic' : undefined,
            textDecoration: style.font?.underline ? 'underline' : undefined,
            textAlign: style.alignment?.horizontal,
            verticalAlign: style.alignment?.vertical,
            borderTop: border(style.border?.top),
            borderRight: border(style.border?.right),
            borderBottom: border(style.border?.bottom),
            borderLeft: border(style.border?.left),
          },
        })
      }
      cells.push(row)
    }
    sheetsData.push({ name: sheetName, cells, colWidths })
  }
  return sheetsData
}

export function ExcelFilePreview({ src, name, downloadUrl }: CommonProps) {
  const { t } = useI18n()
  const [sheets, setSheets] = useState<SheetData[]>([])
  const [active, setActive] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    fetch(src)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.arrayBuffer()
      })
      .then((buf) => {
        if (cancelled) return
        setSheets(parseExcelFile(buf))
        setActive(0)
      })
      .catch((e) => !cancelled && setError(e?.message || t('office.excelFailed')))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [src])

  const sheet = useMemo(() => sheets[active], [sheets, active])
  if (loading) return <Loading />
  if (error || !sheet) return <PreviewError title={t('office.excelFailed')} detail={error || t('office.sheetMissing')} name={name} downloadUrl={downloadUrl} />

  return (
    <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
      {sheets.length > 1 && (
        <div style={{ display: 'flex', gap: 4, overflowX: 'auto', padding: 8, borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-container)' }}>
          {sheets.map((s, i) => (
            <Button key={s.name + i} size="small" type={i === active ? 'primary' : 'default'} onClick={() => setActive(i)}>{s.name}</Button>
          ))}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        <table style={{ minWidth: '100%', borderCollapse: 'separate', borderSpacing: 0, textAlign: 'left' }}>
          <colgroup>{sheet.colWidths.map((w, i) => <col key={i} style={{ width: w }} />)}</colgroup>
          <tbody>
            {sheet.cells.map((row, ri) => (
              <tr key={ri}>{row.map((cell, ci) => {
                if (cell.hidden) return null
                return (
                  <td key={ci} rowSpan={cell.rowSpan > 1 ? cell.rowSpan : undefined} colSpan={cell.colSpan > 1 ? cell.colSpan : undefined}
                    style={{
                      padding: '4px 8px', fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      backgroundColor: cell.style.backgroundColor || '#fff', color: cell.style.color || '#111',
                      fontWeight: cell.style.fontWeight, fontStyle: cell.style.fontStyle, textDecoration: cell.style.textDecoration,
                      textAlign: cell.style.textAlign as any, verticalAlign: cell.style.verticalAlign as any,
                      borderTop: cell.style.borderTop || CELL_DEFAULT_BORDER, borderRight: cell.style.borderRight || CELL_DEFAULT_BORDER,
                      borderBottom: cell.style.borderBottom || CELL_DEFAULT_BORDER, borderLeft: cell.style.borderLeft || CELL_DEFAULT_BORDER,
                    }}>{cell.value}</td>
                )
              })}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface SlideData { html: string; width: number; height: number }
const ROOT_STYLE_PATTERN = /<[^>]+style=(['"])(.*?)\1/i
const WIDTH_PATTERN = /\bwidth\s*:\s*([\d.]+)px\b/i
const HEIGHT_PATTERN = /\bheight\s*:\s*([\d.]+)px\b/i
const DEFAULT_SLIDE_SIZE = { width: 960, height: 540 }

function extractSlideSize(html: string) {
  const style = html.match(ROOT_STYLE_PATTERN)?.[2]
  const width = Number.parseFloat(style?.match(WIDTH_PATTERN)?.[1] || '')
  const height = Number.parseFloat(style?.match(HEIGHT_PATTERN)?.[1] || '')
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0 ? { width, height } : null
}

function SlideMarkup({ slide, scale, title }: { slide: SlideData; scale: number; title: string }) {
  const document = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data: blob:; font-src data:; base-uri \'none\'; form-action \'none\'"><style>html,body{margin:0;overflow:hidden}</style>' + slide.html
  return <iframe title={title} sandbox="" srcDoc={document} tabIndex={-1} style={{ width: slide.width, height: slide.height, border: 0, pointerEvents: 'none', transform: `scale(${scale})`, transformOrigin: 'top left' }} />
}

export function PptxFilePreview({ src, name, downloadUrl }: CommonProps) {
  const { t } = useI18n()
  const containerRef = useRef<HTMLDivElement>(null)
  const [slides, setSlides] = useState<SlideData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [viewportWidth, setViewportWidth] = useState(960)
  const deferredWidth = useDeferredValue(viewportWidth)

  useEffect(() => {
    const node = containerRef.current
    if (!node) return
    const update = () => {
      const padding = parseFloat(getComputedStyle(node).getPropertyValue('--sp-4')) || 0
      setViewportWidth(Math.max(Math.floor(node.clientWidth) - padding * 2, 1))
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(node)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const ac = new AbortController()
    setSlides([])
    setError('')
    setLoading(true)
    async function load() {
      try {
        const { pptxToHtml } = await import('@jvmr/pptx-to-html')
        const res = await fetch(src, { signal: ac.signal })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const buf = await res.arrayBuffer()
        const htmls = await pptxToHtml(buf)
        if (ac.signal.aborted) return
        if (!htmls.length) throw new Error('No slides were rendered')
        const firstSize = extractSlideSize(htmls[0]) || DEFAULT_SLIDE_SIZE
        setSlides(htmls.map((html: string) => {
          const size = extractSlideSize(html) || firstSize
          return { html, width: size.width, height: size.height }
        }))
      } catch (e: any) {
        if (!ac.signal.aborted) setError(e?.message || t('office.pptxFailed'))
      } finally {
        if (!ac.signal.aborted) setLoading(false)
      }
    }
    load()
    return () => ac.abort()
  }, [src])

  if (error) return <PreviewError title={t('office.pptxFailed')} detail={error} name={name} downloadUrl={downloadUrl} />
  return (
    <div ref={containerRef} style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {loading ? <Loading /> : (
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', background: 'var(--bg-base)' }}>
          <div style={{ minHeight: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--sp-5)', padding: 'var(--sp-4)' }}>
            {slides.map((slide, i) => {
              const scale = Math.min(Math.max(deferredWidth / slide.width, 0.1), 1)
              const w = Math.max(Math.round(slide.width * scale), 1)
              const h = Math.max(Math.round(slide.height * scale), 1)
              return (
                <section key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--sp-2)' }}>
                  <span style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dim)' }}>{t('office.page', { page: i + 1 })}</span>
                  <div style={{ width: w, height: h, overflow: 'hidden', background: '#fff' }}>
                    <SlideMarkup slide={slide} scale={scale} title={`${name} ${t('office.page', { page: i + 1 })}`} />
                  </div>
                </section>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function Loading() {
  return <div style={{ height: '100%', display: 'grid', placeItems: 'center' }}><Spin /></div>
}

function PreviewError({ title, detail, name, downloadUrl }: { title: string; detail?: string; name: string; downloadUrl: string }) {
  const { t } = useI18n()
  return (
    <div style={{ height: '100%', display: 'grid', placeItems: 'center', padding: 18, color: 'var(--text-dim)', textAlign: 'center' }}>
      <div>
        <div style={{ color: 'var(--text-bright)', fontWeight: 700, marginBottom: 8 }}>{title}</div>
        {detail && <div style={{ marginBottom: 14 }}>{detail}</div>}
        <Button size="small" type="primary" href={downloadUrl} download={name}>{t('file.downloadFile')}</Button>
      </div>
    </div>
  )
}
