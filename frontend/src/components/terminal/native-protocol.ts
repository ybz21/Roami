// Wire protocol helpers for Roami's native roami-sessiond WebSocket bridge (/api/term/native/:name).

export type SplitDir = 'horizontal' | 'vertical'

export interface LayoutNode {
  id: string
  kind: 'pane' | 'split'
  paneId?: string
  dir?: SplitDir
  ratio?: number
  first?: LayoutNode
  second?: LayoutNode
}

export interface WindowLayout {
  id: string
  name?: string
  layout: LayoutNode
  activePaneId: string
  version: number
}

export interface NativeTerminalMode {
  altScreen: boolean
  mouseOn: boolean
  mouseSgr: boolean
  decckm: boolean
  bracketedPaste: boolean
  cursorX: number
  cursorY: number
  cols: number
  rows: number
}

export type NativeControlEvent =
  | { type: 'snapshot'; seq: number; paneId: string; paneGen: number; data: string; mode?: NativeTerminalMode; controlGen?: number; controller?: string }
  | { type: 'mode'; seq: number; paneId: string; mode: NativeTerminalMode }
  | { type: 'resized'; seq: number; paneId: string; mode: NativeTerminalMode }
  | { type: 'layout_changed'; seq: number; paneId: string; window: WindowLayout }
  | { type: 'control'; seq: number; paneId: string; controlGen: number; controller: string }
  | { type: 'exited'; seq: number; paneId: string; exitCode: number; signal?: string; drained?: boolean }
  | { type: 'resync_needed'; seq: number; paneId: string }
  | { type: 'claimed'; id?: string; lease: { paneId: string; controller: string; controlGen: number } }
  | { type: 'split_ok'; id?: string; window: WindowLayout; paneId: string }
  | { type: 'pong'; id: string }
  | { type: 'error'; id?: string; code?: string; error?: string }

export interface NativeBinaryOutput {
  seq: number
  bytes: Uint8Array
}

// Binary output frames carry an 8-byte big-endian uint64 sequence number followed by raw VT bytes.
export function decodeNativeBinaryFrame(buf: ArrayBuffer): NativeBinaryOutput | null {
  if (buf.byteLength < 8) return null
  const view = new DataView(buf)
  const hi = view.getUint32(0, false)
  const lo = view.getUint32(4, false)
  const seq = hi * 0x100000000 + lo
  return { seq, bytes: new Uint8Array(buf, 8) }
}

export function parseNativeControlEvent(raw: string): NativeControlEvent | null {
  if (!raw.startsWith('{')) return null
  try {
    const parsed = JSON.parse(raw) as Partial<NativeControlEvent>
    if (!parsed || typeof parsed.type !== 'string') return null
    return parsed as NativeControlEvent
  } catch {
    return null
  }
}

// Suppress automatic DA1/DA2/DSR/OSC terminal query responses emitted by xterm.js onData.
// roami-sessiond's server-side VT is the sole responder so multi-client attach never duplicates replies.
const AUTO_QUERY_REPLY_RE = /^\x1b(?:\[\?[0-9;]*c|\[>[0-9;]*c|\[\d+;\d+R|\[0n|\](?:10|11);rgb:[0-9a-fA-F/]+(?:\x07|\x1b\\))$/

export function isTerminalAutoQueryReply(input: string): boolean {
  return AUTO_QUERY_REPLY_RE.test(input)
}

export function clampSplitRatio(ratio: number, min = 0.15, max = 0.85): number {
  if (!Number.isFinite(ratio)) return 0.5
  return Math.max(min, Math.min(max, ratio))
}

export function collectPaneIds(node: LayoutNode | null | undefined): string[] {
  if (!node) return []
  if (node.kind === 'pane') return node.paneId ? [node.paneId] : []
  return [...collectPaneIds(node.first), ...collectPaneIds(node.second)]
}
