import type { DuplexTransport } from '../../p2p/transport'

interface Frame {
  source: DuplexTransport
  data: ArrayBuffer
  w: number
  h: number
  seq: number
}

export function connectBrowserStream(
  image: HTMLImageElement,
  open: () => DuplexTransport,
  onFrame: (frame: { w: number; h: number; bytes: number }) => void,
): DuplexTransport {
  let current: DuplexTransport | null = null
  let stopped = false
  let retry = 0
  let retryTimer: ReturnType<typeof setTimeout> | undefined
  let frameTimer: ReturnType<typeof setTimeout> | undefined
  let refreshTimer: ReturnType<typeof setTimeout> | undefined
  let pending: Frame | null = null
  let loading: { frame: Frame; url: string } | null = null
  let visibleURL: string | null = null
  let lastActivity = Date.now()
  const watchdog = setInterval(() => {
    if (current && Date.now() - lastActivity >= 10000) reconnect()
  }, 2000)

  const stream: DuplexTransport = {
    get kind() { return current?.kind || 'frp' },
    onopen: () => {}, onclose: () => {}, onmessage: () => {},
    send: data => current?.send(data),
    close: () => {
      stopped = true
      clearTimeout(retryTimer)
      clearInterval(watchdog)
      clearFrameTimers()
      detach()
      image.removeEventListener('load', loaded)
      image.removeEventListener('error', failed)
      image.removeAttribute('src')
      if (visibleURL) URL.revokeObjectURL(visibleURL)
      visibleURL = null
    },
  }
  const ack = (frame: Frame) => frame.source.send(JSON.stringify({ type: 'ack', n: frame.seq }))
  const clearFrameTimers = () => { clearTimeout(frameTimer); clearTimeout(refreshTimer) }
  const detach = () => {
    if (current) {
      current.onopen = () => {}; current.onmessage = () => {}; current.onclose = () => {}
      current.close()
      current = null
    }
    pending = null
    if (loading) {
      const url = loading.url
      loading = null
      if (visibleURL) image.src = visibleURL
      else image.removeAttribute('src')
      URL.revokeObjectURL(url)
    }
  }
  const draw = () => {
    if (loading || !pending || stopped) return
    const frame = pending
    pending = null
    const url = URL.createObjectURL(new Blob([new Uint8Array(frame.data, 6)], { type: 'image/jpeg' }))
    loading = { frame, url }
    image.src = url
  }
  function loaded() {
    if (!loading) return
    const { frame, url } = loading
    loading = null
    if (visibleURL) URL.revokeObjectURL(visibleURL)
    visibleURL = url
    retry = 0
    clearFrameTimers()
    ack(frame)
    onFrame({ w: frame.w, h: frame.h, bytes: frame.data.byteLength })
    draw()
  }
  function failed() {
    if (!loading) return
    const { frame, url } = loading
    loading = null
    if (visibleURL) image.src = visibleURL
    else image.removeAttribute('src')
    URL.revokeObjectURL(url)
    ack(frame)
    draw()
  }
  const reconnect = () => {
    if (stopped || !current) return
    clearFrameTimers()
    detach()
    stream.onclose()
    retryTimer = setTimeout(start, Math.min(1000 * 2 ** retry++, 10000))
  }
  const start = () => {
    if (stopped) return
    const source = open()
    current = source
    lastActivity = Date.now()
    // An open socket can still have no renderer or no decodable first frame.
    frameTimer = setTimeout(reconnect, 15000)
    source.onopen = () => {
      if (stopped || current !== source) return
      lastActivity = Date.now()
      stream.onopen()
      refreshTimer = setTimeout(() => source.send(JSON.stringify({ type: 'refresh' })), 3000)
    }
    source.onclose = reconnect
    source.onmessage = data => {
      if (stopped || current !== source) return
      lastActivity = Date.now()
      if (typeof data === 'string') { stream.onmessage(data); return }
      if (data.byteLength <= 6) return
      const view = new DataView(data)
      const w = view.getUint16(0, true), h = view.getUint16(2, true), seq = view.getUint16(4, true)
      if (!w || !h) { ack({ source, data, w, h, seq }); return }
      // Keep one decode in flight; ACK after display so fast producers cannot starve image loading.
      if (pending) ack(pending)
      pending = { source, data, w, h, seq }
      draw()
    }
  }
  image.addEventListener('load', loaded)
  image.addEventListener('error', failed)
  start()
  return stream
}
