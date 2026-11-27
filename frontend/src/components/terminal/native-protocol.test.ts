import { describe, expect, it } from 'vitest'
import {
  clampSplitRatio,
  collectPaneIds,
  decodeNativeBinaryFrame,
  isTerminalAutoQueryReply,
  parseNativeControlEvent,
  type LayoutNode,
} from './native-protocol'

describe('native-protocol', () => {
  it('decodes 8-byte big-endian sequenced binary output frames', () => {
    const payload = new TextEncoder().encode('你好 Roami')
    const buf = new ArrayBuffer(8 + payload.length)
    const view = new DataView(buf)
    view.setUint32(0, 0, false)
    view.setUint32(4, 42, false)
    new Uint8Array(buf, 8).set(payload)

    const decoded = decodeNativeBinaryFrame(buf)
    expect(decoded).not.toBeNull()
    expect(decoded!.seq).toBe(42)
    expect(new TextDecoder().decode(decoded!.bytes)).toBe('你好 Roami')
    expect(decodeNativeBinaryFrame(new ArrayBuffer(4))).toBeNull()
  })

  it('filters xterm automatic DA/DSR/OSC query replies while keeping real user input', () => {
    expect(isTerminalAutoQueryReply('\x1b[?62;c')).toBe(true)
    expect(isTerminalAutoQueryReply('\x1b[>0;10;1c')).toBe(true)
    expect(isTerminalAutoQueryReply('\x1b[12;34R')).toBe(true)
    expect(isTerminalAutoQueryReply('\x1b[0n')).toBe(true)
    expect(isTerminalAutoQueryReply('\x1b]10;rgb:ffff/ffff/ffff\x07')).toBe(true)

    expect(isTerminalAutoQueryReply('a')).toBe(false)
    expect(isTerminalAutoQueryReply('\x1b[A')).toBe(false)
    expect(isTerminalAutoQueryReply('\r')).toBe(false)
    expect(isTerminalAutoQueryReply('hello world')).toBe(false)
  })

  it('parses control frames and collects pane IDs from nested split trees', () => {
    const tree: LayoutNode = {
      id: 's1',
      kind: 'split',
      dir: 'horizontal',
      ratio: 0.5,
      first: { id: 'n1', kind: 'pane', paneId: 'p1' },
      second: {
        id: 's2',
        kind: 'split',
        dir: 'vertical',
        ratio: 0.5,
        first: { id: 'n2', kind: 'pane', paneId: 'p2' },
        second: { id: 'n3', kind: 'pane', paneId: 'p3' },
      },
    }
    expect(collectPaneIds(tree)).toEqual(['p1', 'p2', 'p3'])
    expect(clampSplitRatio(0.01)).toBe(0.15)
    expect(clampSplitRatio(0.99)).toBe(0.85)
    expect(clampSplitRatio(Number.NaN)).toBe(0.5)

    const ev = parseNativeControlEvent(JSON.stringify({
      type: 'layout_changed',
      seq: 7,
      paneId: 'p1',
      window: { id: 'w1', layout: tree, activePaneId: 'p3', version: 3 },
    }))
    expect(ev?.type).toBe('layout_changed')
  })
})
