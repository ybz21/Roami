// A busy unrelated renderer must not hold up a new Playwright connection.
export class ScopedCDP {
  constructor(socket, { timeoutMs = 10000 } = {}) {
    this.socket = socket
    this.timeoutMs = timeoutMs
    this.nextId = -1
    this.pending = new Map()
    this.autoAttach = new Set()
    this.closed = false
    socket.on('message', data => this.receive(JSON.parse(data.toString())))
    socket.on('close', () => {
      this.closed = true
      for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(new Error('CHROME_CONNECTION_CLOSED')) }
      this.pending.clear()
      this.onclose?.()
    })
    socket.on('error', () => this.close())
  }
  static async connect(url) {
    const { default: WebSocket } = await import('ws')
    const socket = new WebSocket(url, { handshakeTimeout: 10000, maxPayload: 64 * 1024 * 1024 })
    const connection = new ScopedCDP(socket)
    await new Promise((resolve, reject) => {
      const failed = error => { socket.removeListener('open', ready); reject(error) }
      const ready = () => { socket.removeListener('error', failed); resolve() }
      socket.once('open', ready)
      socket.once('error', failed)
    })
    return connection
  }
  request(method, params = {}) {
    const id = this.nextId--
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('CHROME_CONNECTION_TIMEOUT')) }, this.timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      try { this.socket.send(JSON.stringify({ id, method, params })) } catch (error) {
        clearTimeout(timer); this.pending.delete(id); reject(error)
      }
    })
  }
  send(message) {
    if (!message.sessionId && message.method === 'Target.setAutoAttach' && message.params.autoAttach) {
      this.autoAttach.add(message.id)
      message = { ...message, params: { ...message.params, filter: [{ exclude: true }], waitForDebuggerOnStart: false } }
    }
    this.socket.send(JSON.stringify(message))
  }
  async receive(message) {
    if (this.closed) return
    const pending = this.pending.get(message.id)
    if (pending) {
      clearTimeout(pending.timer); this.pending.delete(message.id)
      if (message.error) pending.reject(new Error(message.error.message))
      else pending.resolve(message.result)
      return
    }
    if (message.id < 0) return
    if (this.autoAttach.delete(message.id) && !message.error && this.targetId) {
      try { await this.request('Target.attachToTarget', { targetId: this.targetId, flatten: true }) }
      catch (error) { message = { id: message.id, error: { code: -32000, message: error.message } } }
    }
    if (!this.closed) this.onmessage?.(message)
  }
  close() { this.socket.close() }
}

export async function connectTarget(url, targetId) {
  const { chromium } = await import('playwright-core')
  const transport = await ScopedCDP.connect(url)
  transport.targetId = targetId
  try { return await chromium.connectOverCDP(transport, { timeout: 10000, noDefaults: true }) }
  catch (error) { transport.close(); throw error }
}

export function selectTarget(targets, flags) {
  if (flags.target != null) {
    if (flags.tab != null || flags.url) throw new Error('CHROME_TARGET_SELECTION_CONFLICT')
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(flags.target)) throw new Error('CHROME_TARGET_INVALID')
    const target = targets.find(t => t.targetId === flags.target)
    if (!target) throw new Error('CHROME_TARGET_NOT_FOUND')
    return target
  }
  const target = flags.tab != null ? targets[Number(flags.tab)] : flags.url ? targets.find(t => t.url.includes(flags.url)) : targets[0]
  if (!target) throw new Error('CHROME_TARGET_NOT_FOUND')
  return target
}
