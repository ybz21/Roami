import { describe, expect, it, vi } from 'vitest'
import type { WebglAddon } from '@xterm/addon-webgl'
import type { Terminal } from '@xterm/xterm'
import { synchronizeTerminalAtlas } from './terminal-atlas'

function makeAtlas() {
  const listeners = new Set<() => void>()
  return {
    clearTexture: vi.fn(),
    onRemoveTextureAtlasCanvas: (listener: () => void) => {
      listeners.add(listener)
      return { dispose: () => listeners.delete(listener) }
    },
    merge: () => { for (const listener of listeners) listener() },
  }
}

function makeTerminal(atlas = makeAtlas()) {
  const term = { rows: 24, refresh: vi.fn() }
  const renderer = {
    _charAtlas: atlas,
    _clearModel: vi.fn(),
    _glyphRenderer: { value: { setAtlas: vi.fn() } },
    renderRows: vi.fn(),
  }
  const draw = renderer.renderRows
  const dispose = synchronizeTerminalAtlas(term as unknown as Terminal, { _renderer: renderer } as unknown as WebglAddon)
  renderer.renderRows(0, 23)
  vi.clearAllMocks()
  return { term, renderer, draw, dispose }
}

describe('shared terminal atlas invalidation', () => {
  it('rebuilds every owner after a sibling clears the shared atlas', async () => {
    const atlas = makeAtlas()
    const first = makeTerminal(atlas)
    const second = makeTerminal(atlas)
    atlas.clearTexture()
    await Promise.resolve()
    for (const { term, renderer, draw } of [first, second]) {
      expect(term.refresh).toHaveBeenCalledWith(0, 23)
      renderer.renderRows(12, 12)
      expect(renderer._clearModel).toHaveBeenCalledWith(true)
      expect(renderer._glyphRenderer.value.setAtlas).toHaveBeenCalledWith(atlas)
      expect(draw).toHaveBeenCalledWith(0, 23)
    }
  })

  it('coalesces page merge notifications and invalidates GPU uploads', async () => {
    const atlas = makeAtlas()
    const { term, renderer, draw } = makeTerminal(atlas)
    for (let i = 0; i < 4; i++) atlas.merge()
    expect(term.refresh).not.toHaveBeenCalled()
    await Promise.resolve()
    expect(term.refresh).toHaveBeenCalledTimes(1)
    renderer.renderRows(3, 3)
    expect(renderer._glyphRenderer.value.setAtlas).toHaveBeenCalledWith(atlas)
    expect(draw).toHaveBeenCalledWith(0, 23)
  })

  it('keeps incremental updates when the atlas layout has not changed', () => {
    const { renderer, draw } = makeTerminal()
    renderer.renderRows(3, 3)
    expect(renderer._clearModel).not.toHaveBeenCalled()
    expect(renderer._glyphRenderer.value.setAtlas).not.toHaveBeenCalled()
    expect(draw).toHaveBeenCalledWith(3, 3)
  })

  it('unsubscribes from old atlases on theme or DPR changes', async () => {
    const previous = makeAtlas()
    const { term, renderer } = makeTerminal(previous)
    const next = makeAtlas()
    renderer._charAtlas = next
    renderer.renderRows(3, 3)
    expect(renderer._glyphRenderer.value.setAtlas).toHaveBeenCalledWith(next)
    previous.clearTexture()
    await Promise.resolve()
    expect(term.refresh).not.toHaveBeenCalled()
    next.clearTexture()
    await Promise.resolve()
    expect(term.refresh).toHaveBeenCalledTimes(1)
  })

  it('does not refresh disposed terminals, including a pending merge notification', async () => {
    const atlas = makeAtlas()
    const { term, renderer, draw, dispose } = makeTerminal(atlas)
    atlas.merge()
    dispose()
    await Promise.resolve()
    expect(term.refresh).not.toHaveBeenCalled()
    expect(renderer.renderRows).toBe(draw)
  })
})
