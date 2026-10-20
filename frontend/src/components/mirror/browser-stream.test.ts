// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DuplexTransport } from '../../p2p/transport'
import { connectBrowserStream } from './browser-stream'

function frame(seq: number) {
  const data = new ArrayBuffer(10)
  const view = new DataView(data)
  view.setUint16(0, 1280, true); view.setUint16(2, 800, true); view.setUint16(4, seq, true)
  return data
}

function fixture() {
  const sources: DuplexTransport[] = []
  const open = vi.fn(() => {
    const source: DuplexTransport = {
      kind: 'frp', onopen: () => {}, onclose: () => {}, onmessage: () => {}, send: vi.fn(), close: vi.fn(),
    }
    sources.push(source)
    return source
  })
  const image = document.createElement('img')
  const onFrame = vi.fn()
  const stream = connectBrowserStream(image, open, onFrame)
  return { sources, open, image, onFrame, stream }
}

beforeEach(() => {
  vi.useFakeTimers()
  let next = 0
  URL.createObjectURL = vi.fn(() => 'blob:frame-' + next++)
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers() })

describe('browser mirror recovery', () => {
  it('waits for image display before ACK and keeps only the latest waiting frame', () => {
    const { sources, image, onFrame, stream } = fixture()
    const source = sources[0]
    source.onmessage(frame(1))
    const first = image.src
    source.onmessage(frame(2))
    source.onmessage(frame(3))
    expect(image.src).toBe(first)
    expect(source.send).toHaveBeenCalledOnce()
    expect(source.send).toHaveBeenCalledWith(JSON.stringify({ type: 'ack', n: 2 }))
    expect(onFrame).not.toHaveBeenCalled()
    image.dispatchEvent(new Event('load'))
    expect(source.send).toHaveBeenCalledWith(JSON.stringify({ type: 'ack', n: 1 }))
    expect(onFrame).toHaveBeenCalledOnce()
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith(first)
    image.dispatchEvent(new Event('load'))
    expect(source.send).toHaveBeenCalledWith(JSON.stringify({ type: 'ack', n: 3 }))
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(first)
    stream.close()
  })

  it('reconnects after a disconnect and ignores callbacks from the old channel', async () => {
    const { sources, open, stream, onFrame } = fixture()
    const closed = vi.fn(); stream.onclose = closed
    const stale = sources[0].onmessage
    sources[0].onclose()
    expect(closed).toHaveBeenCalledOnce()
    await vi.advanceTimersByTimeAsync(1000)
    expect(open).toHaveBeenCalledTimes(2)
    stale(frame(1))
    expect(onFrame).not.toHaveBeenCalled()
    stream.close()
    await vi.advanceTimersByTimeAsync(30000)
    expect(open).toHaveBeenCalledTimes(2)
  })

  it('requests a first frame and retries an open channel that never produces one', async () => {
    const { sources, open, stream, onFrame } = fixture()
    sources[0].onopen()
    await vi.advanceTimersByTimeAsync(3000)
    expect(sources[0].send).toHaveBeenCalledWith(JSON.stringify({ type: 'refresh' }))
    for (let i = 0; i < 12; i++) {
      sources[0].onmessage('{"type":"pong","t":0}')
      await vi.advanceTimersByTimeAsync(1000)
    }
    await vi.advanceTimersByTimeAsync(1000)
    expect(open).toHaveBeenCalledTimes(2)
    expect(onFrame).not.toHaveBeenCalled()
    stream.close()
  })

  it('keeps a static displayed page connected while heartbeats continue', async () => {
    const { sources, open, image, stream } = fixture()
    sources[0].onopen(); sources[0].onmessage(frame(1)); image.dispatchEvent(new Event('load'))
    for (let i = 0; i < 20; i++) {
      sources[0].onmessage('{"type":"pong","t":0}')
      await vi.advanceTimersByTimeAsync(1000)
    }
    expect(open).toHaveBeenCalledOnce()
    stream.close()
  })

  it('recovers a silent channel and releases failed image frames', async () => {
    const { sources, open, image, stream, onFrame } = fixture()
    sources[0].onmessage(frame(1)); image.dispatchEvent(new Event('error'))
    expect(onFrame).not.toHaveBeenCalled()
    expect(sources[0].send).toHaveBeenCalledWith(JSON.stringify({ type: 'ack', n: 1 }))
    await vi.advanceTimersByTimeAsync(11000)
    expect(open).toHaveBeenCalledTimes(2)
    stream.close()
  })
})
