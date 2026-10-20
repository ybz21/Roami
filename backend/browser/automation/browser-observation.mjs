import { createHash } from 'node:crypto'
import { writeFile } from 'node:fs/promises'

export async function discoverBrowser(endpoint, fetchVersion = fetch) {
  const address = new URL(endpoint)
  let websocket = address
  if (address.protocol === 'http:' || address.protocol === 'https:') {
    const response = await fetchVersion(endpoint.replace(/\/$/, '') + '/json/version', {
      signal: AbortSignal.timeout(3000), redirect: 'error',
    })
    if (!response.ok) throw new Error('CHROME_BROWSER_IDENTITY_UNAVAILABLE')
    const chunks = []; let size = 0
    for await (const chunk of response.body) {
      size += chunk.length
      if (size > 64_000) throw new Error('CHROME_BROWSER_IDENTITY_UNAVAILABLE')
      chunks.push(chunk)
    }
    websocket = new URL(JSON.parse(Buffer.concat(chunks).toString('utf8')).webSocketDebuggerUrl)
  }
  const identity = websocket.pathname.match(/^\/devtools\/browser\/([A-Za-z0-9_-]{1,128})$/)
  if (!['ws:', 'wss:'].includes(websocket.protocol) || !identity) throw new Error('CHROME_BROWSER_IDENTITY_UNAVAILABLE')
  return { id: identity[1], websocketUrl: websocket.toString() }
}

export async function browserIdentity(endpoint, fetchVersion = fetch) {
  return (await discoverBrowser(endpoint, fetchVersion)).id
}

export function pngDimensions(body) {
  if (body.length < 24 || body.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') throw new Error('CHROME_SCREENSHOT_INVALID')
  const width = body.readUInt32BE(16), height = body.readUInt32BE(20)
  if (!width || !height || width > 32768 || height > 32768) throw new Error('CHROME_SCREENSHOT_INVALID')
  return { width, height }
}

async function scene(page, session) {
  const { frameTree } = await session.send('Page.getFrameTree')
  const document = await page.evaluate(() => {
    const html = document.documentElement?.outerHTML || ''
    if (html.length > 2_000_000) return { oversized: true }
    const selector = element => {
      if (element.id) return '#' + CSS.escape(element.id)
      const parts = []
      for (let current = element; current && current !== document.body; current = current.parentElement) {
        if (parts.length >= 24) return null
        const index = [...current.parentElement.children].indexOf(current) + 1
        parts.unshift(CSS.escape(current.tagName.toLowerCase()) + ':nth-child(' + index + ')')
      }
      return 'body > ' + parts.join(' > ')
    }
    const visible = element => {
      const rect = element.getBoundingClientRect(), style = getComputedStyle(element)
      return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0
        && rect.top < innerHeight && rect.left < innerWidth && style.visibility !== 'hidden' && style.display !== 'none'
    }
    const candidates = [...document.querySelectorAll('a,button,input,select,textarea,[role="button"],[contenteditable="true"]')].filter(visible)
    const link = element => {
      if (element.tagName !== 'A' || !element.getAttribute('href')) return {}
      try {
        const url = new URL(element.getAttribute('href'), document.baseURI)
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.href.length > 2400) return {}
        return { href: url.href }
      } catch { return {} }
    }
    const controls = candidates.slice(0, 64).map(element => ({
        selector: selector(element), tag: element.tagName.toLowerCase(),
        ...link(element),
        label: (element.getAttribute('aria-label') || element.getAttribute('placeholder') || '').slice(0, 160),
        text: (element.innerText || '').slice(0, 160),
        value: element.type === 'password' ? '[redacted]' : String(element.value ?? '').slice(0, 160),
        disabled: !!element.disabled,
      }))
    const values = [...document.querySelectorAll('input,textarea,select,[contenteditable="true"]')].map(element => [element.isContentEditable ? element.innerHTML : element.value, element.checked])
    if (values.reduce((size, item) => size + (item[0]?.length || 0), html.length) > 2_000_000) return { oversized: true }
    return {
      html, values, controls, controlsTruncated: candidates.length > 64, scope: 'main_frame', iframeCount: document.querySelectorAll('iframe,frame').length, url: location.href, title: document.title.slice(0, 300),
      domText: (document.body?.innerText || '').slice(0, 8000),
      viewportSize: { width: innerWidth, height: innerHeight }, deviceScale: devicePixelRatio,
      scroll: { x: scrollX, y: scrollY }, focused: {
        html: document.activeElement?.outerHTML?.slice(0, 1000),
        identity: [document.activeElement?.tagName, document.activeElement?.id, document.activeElement?.name, document.activeElement?.type],
        start: document.activeElement?.selectionStart, end: document.activeElement?.selectionEnd,
        hasFocus: document.hasFocus(), selection: window.getSelection()?.toString().slice(0, 1000),
      },
    }
  })
  if (document.oversized) throw new Error('CHROME_SCENE_LIMIT')
  const signature = createHash('sha256').update(JSON.stringify({ loader: frameTree.frame.loaderId, frame: frameTree.frame.id, ...document })).digest('hex')
  const navigationFocus = { ...document.focused }
  delete navigationFocus.html
  const navigationSignature = createHash('sha256').update(JSON.stringify({ kind: 'navigation', loader: frameTree.frame.loaderId, frame: frameTree.frame.id, url: document.url, values: document.values, focused: navigationFocus })).digest('hex')
  const { html, values, focused, ...observation } = document
  if (observation.url.length > 2400) { observation.url = observation.url.slice(0, 2400); observation.urlTruncated = true }
  while (Buffer.byteLength(JSON.stringify(observation)) > 48_000 && observation.controls.length) {
    observation.controls.pop(); observation.controlsTruncated = true
  }
  if (Buffer.byteLength(JSON.stringify(observation)) > 48_000) throw new Error('CHROME_SCENE_LIMIT')
  return { ...observation, signature, navigationSignature, capturedMs: Date.now() }
}

export async function observePage(page, screenshotPath, { timeoutMs = 5000 } = {}) {
  const session = await page.context().newCDPSession(page)
  let timer
  const deadline = new Promise((_, reject) => {
    if (timeoutMs) timer = setTimeout(() => reject(new Error('CHROME_OBSERVATION_TIMEOUT')), timeoutMs)
  })
  const bounded = operation => Promise.race([operation, deadline])
  try {
    const before = await bounded(scene(page, session))
    if (!screenshotPath) return before
    const screenshot = await bounded(session.send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false }))
    const body = Buffer.from(screenshot.data, 'base64'), size = pngDimensions(body)
    const after = await bounded(scene(page, session))
    if (after.signature !== before.signature) throw new Error('CHROME_SCENE_CHANGED')
    await writeFile(screenshotPath, body, { mode: 0o600, flag: 'wx' })
    return { ...after, screenshot: { path: screenshotPath, ...size,
      scaleX: size.width / after.viewportSize.width, scaleY: size.height / after.viewportSize.height } }
  } finally {
    clearTimeout(timer)
    await Promise.race([session.detach().catch(() => {}), new Promise(resolve => setTimeout(resolve, 250))])
  }
}
