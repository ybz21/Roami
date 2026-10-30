import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist/legacy/build/pdf.mjs'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import { Input, Select } from 'antd'
import { ChevronDown, ChevronLeft, ChevronRight, ZoomInIcon, ZoomOutIcon } from '../../icons'
import { useI18n } from '../../i18n'
import './document-preview.css'

GlobalWorkerOptions.workerSrc = workerUrl

type ScaleMode = 'page' | 'width' | number
const zoomSteps = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4]

export default function PdfDocument({ src, name }: { src: string; name: string }) {
  const { t, locale } = useI18n()
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(1), [pageInput, setPageInput] = useState('1'), [retry, setRetry] = useState(0)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [scaleMode, setScaleMode] = useState<ScaleMode>('page'), [scale, setScale] = useState(1)
  const [failed, setFailed] = useState(false), [rendering, setRendering] = useState(true)
  const [ready, setReady] = useState(false)
  const container = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const element = container.current
    if (!element) return
    const measure = () => setSize(previous => {
      const width = element.clientWidth, height = element.clientHeight
      return previous.width === width && previous.height === height ? previous : { width, height }
    })
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    measure()
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    let stopped = false
    setDocument(null); setPage(1); setPageInput('1'); setFailed(false); setRendering(true); setReady(false)
    const loading = getDocument({ url: src, withCredentials: true, useSystemFonts: true, useWasm: false,
      cMapUrl: `${import.meta.env.BASE_URL}pdfjs/cmaps/`, cMapPacked: true,
      standardFontDataUrl: `${import.meta.env.BASE_URL}pdfjs/standard_fonts/`,
    })
    void loading.promise.then(pdf => { if (!stopped) setDocument(pdf) }).catch(() => { if (!stopped) setFailed(true) })
    return () => { stopped = true; void loading.destroy() }
  }, [src, retry])
  useEffect(() => {
    if (!document || !size.width || !size.height || !canvas.current) return
    let stopped = false
    let render: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined
    setRendering(true); setFailed(false)
    void document.getPage(page).then(async pdfPage => {
      if (stopped || !canvas.current) return
      const base = pdfPage.getViewport({ scale: 1 })
      const nextScale = scaleMode === 'page' ? Math.min(size.width / base.width, size.height / base.height)
        : scaleMode === 'width' ? size.width / base.width : scaleMode
      const viewport = pdfPage.getViewport({ scale: nextScale })
      // Bound mobile canvas memory independently of display density.
      const density = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(8_000_000 / (viewport.width * viewport.height)))
      const element = canvas.current
      // Keep the displayed page and its scrollbar until the replacement is complete.
      const buffer = element.ownerDocument.createElement('canvas')
      buffer.width = Math.max(1, Math.floor(viewport.width * density))
      buffer.height = Math.max(1, Math.floor(viewport.height * density))
      render = pdfPage.render({ canvas: buffer, viewport, transform: [density, 0, 0, density, 0, 0] })
      await render.promise
      render = undefined
      if (stopped) return
      const context = element.getContext('2d')
      if (!context) throw new Error('Canvas unavailable')
      element.width = buffer.width
      element.height = buffer.height
      element.style.width = `${viewport.width}px`
      element.style.height = `${viewport.height}px`
      context.drawImage(buffer, 0, 0)
      setScale(nextScale)
      setReady(true); setRendering(false)
    }).catch(() => { if (!stopped) { setFailed(true); setRendering(false) } })
    return () => { stopped = true; render?.cancel() }
  }, [document, page, size, scaleMode])
  const navigate = (next: number) => {
    if (!document) return
    const target = Math.min(document.numPages, Math.max(1, next))
    setPage(target); setPageInput(String(target))
    if (target !== page && container.current) {
      container.current.scrollTop = 0; container.current.scrollLeft = 0
    }
  }
  const jump = () => navigate(/^\d+$/.test(pageInput) ? Number(pageInput) : page)
  const zoomOut = [...zoomSteps].reverse().find(value => value < scale - 0.001)
  const zoomIn = zoomSteps.find(value => value > scale + 0.001)
  const percent = (value: number) => new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(value)
  return <div className="pdf-document">
    {document && <div className="pdf-document-toolbar">
      {document.numPages > 1 && <div className="pdf-document-pages">
        <button type="button" className="tt-act" aria-label={t('document.previousPage')} disabled={page === 1 || rendering} onClick={() => navigate(page - 1)}><ChevronLeft size={20} /></button>
        <Input className="pdf-document-page-input" aria-label={t('document.jumpToPage')} inputMode="numeric" enterKeyHint="go" autoComplete="off" value={pageInput} onFocus={event => event.target.select()}
          onChange={event => setPageInput(event.target.value)} onBlur={jump}
          onPressEnter={event => { jump(); event.currentTarget.blur() }}
          onKeyDown={event => { if (event.key === 'Escape') { setPageInput(String(page)) } }} />
        <span aria-label={t('document.page', { page, total: document.numPages })}>{t('document.pageTotal', { total: new Intl.NumberFormat(locale).format(document.numPages) })}</span>
        <button type="button" className="tt-act" aria-label={t('document.nextPage')} disabled={page === document.numPages || rendering} onClick={() => navigate(page + 1)}><ChevronRight size={20} /></button>
      </div>}
      <div className="pdf-document-zoom">
        <button type="button" className="tt-act" aria-label={t('file.imgZoomOut')} disabled={zoomOut === undefined || rendering} onClick={() => setScaleMode(zoomOut!)}><ZoomOutIcon size={20} /></button>
        <Select className="pdf-document-scale" aria-label={t('document.scale')} value={scaleMode} onChange={setScaleMode} popupMatchSelectWidth={false} suffixIcon={<ChevronDown size={16} />}
          virtual={false} classNames={{ popup: { root: 'pdf-document-scale-options' } }}
          options={[
            { value: 'page', label: t('document.fitPage') }, { value: 'width', label: t('document.fitWidth') },
            ...zoomSteps.map(value => ({ value, label: percent(value) })),
          ]} />
        <button type="button" className="tt-act" aria-label={t('file.imgZoomIn')} disabled={zoomIn === undefined || rendering} onClick={() => setScaleMode(zoomIn!)}><ZoomInIcon size={20} /></button>
      </div>
    </div>}
    <div className="pdf-document-scroll" ref={container}>
      {failed ? <p role="alert">{t('document.loadFailed')} <button type="button" className="tt-act" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button></p> : <>
        {rendering && !ready && <p className="pdf-document-loading" role="status">{t('common.loading')}</p>}
        <canvas ref={canvas} role="img" aria-label={`${name} ${t('office.page', { page })}`} hidden={!ready} />
      </>}
    </div>
  </div>
}
