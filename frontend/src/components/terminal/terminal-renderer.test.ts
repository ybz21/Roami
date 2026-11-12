import { describe, expect, it, vi } from 'vitest'
import type { WebglAddon } from '@xterm/addon-webgl'
import { createTerminalRenderer, disposeTerminalWebgl } from './terminal-renderer'

function fixture() {
  const releases: ReturnType<typeof vi.fn>[] = []
  const losses: (() => void)[] = []
  const create = vi.fn((lost: () => void) => {
    const release = vi.fn()
    releases.push(release)
    losses.push(lost)
    return release
  })
  const refresh = vi.fn()
  return { renderer: createTerminalRenderer(create, refresh), create, refresh, releases, losses }
}

describe('terminal renderer lifetime', () => {
  it('allocates only the visible renderer among 32 open terminals', () => {
    const terminals = Array.from({ length: 32 }, fixture)
    terminals.forEach((t, i) => t.renderer.setActive(i === 0))
    expect(terminals.reduce((n, t) => n + t.create.mock.calls.length, 0)).toBe(1)
    terminals[0].renderer.setActive(false)
    terminals[31].renderer.setActive(true)
    expect(terminals[0].releases[0]).toHaveBeenCalledTimes(1)
    expect(terminals[31].create).toHaveBeenCalledTimes(1)
    terminals.forEach(t => t.renderer.dispose())
  })

  it('does not reallocate on repeated activation or create a hidden renderer on rebuild', () => {
    const t = fixture()
    t.renderer.rebuild()
    expect(t.create).not.toHaveBeenCalled()
    t.renderer.setActive(true)
    t.renderer.setActive(true)
    expect(t.create).toHaveBeenCalledTimes(1)
    t.renderer.setActive(false)
    t.renderer.rebuild()
    expect(t.create).toHaveBeenCalledTimes(1)
  })

  it('falls back after context loss without competing to recreate GPU contexts', () => {
    const t = fixture()
    t.renderer.setActive(true)
    t.losses[0]()
    expect(t.releases[0]).toHaveBeenCalledTimes(1)
    expect(t.refresh).toHaveBeenCalledTimes(1)
    expect(t.create).toHaveBeenCalledTimes(1)
    t.renderer.rebuild()
    expect(t.create).toHaveBeenCalledTimes(2)
  })

  it('ignores delayed loss callbacks from an old renderer', () => {
    const t = fixture()
    t.renderer.setActive(true)
    t.renderer.rebuild()
    t.losses[0]()
    expect(t.releases[1]).not.toHaveBeenCalled()
    expect(t.refresh).not.toHaveBeenCalled()
    t.renderer.dispose()
    t.losses[1]()
    t.renderer.setActive(true)
    t.renderer.rebuild()
    expect(t.releases[1]).toHaveBeenCalledTimes(1)
    expect(t.create).toHaveBeenCalledTimes(2)
  })

  it('contains GPU allocation and cleanup failures', () => {
    const t = createTerminalRenderer(() => { throw new Error('GPU unavailable') }, vi.fn())
    expect(() => t.setActive(true)).not.toThrow()
    const other = createTerminalRenderer(() => () => { throw new Error('lost') }, vi.fn())
    other.setActive(true)
    expect(() => other.dispose()).not.toThrow()
  })

  it('releases a renderer that loses its context during allocation', () => {
    const release = vi.fn()
    const t = createTerminalRenderer(lost => { lost(); return release }, vi.fn())
    t.setActive(true)
    expect(release).toHaveBeenCalledTimes(1)
    t.dispose()
    expect(release).toHaveBeenCalledTimes(1)
  })
})

describe('eager WebGL reclamation', () => {
  it.each([false, true])('reclaims the context even when addon disposal throws: %s', fail => {
    const loseContext = vi.fn()
    const dispose = vi.fn(() => { if (fail) throw new Error('dispose failed') })
    const addon = { dispose, _renderer: { _gl: { getExtension: vi.fn(() => ({ loseContext })) } } }
    try { disposeTerminalWebgl(addon as unknown as WebglAddon) } catch { /* asserted below */ }
    expect(dispose).toHaveBeenCalledTimes(1)
    expect(loseContext).toHaveBeenCalledTimes(1)
    expect(dispose.mock.invocationCallOrder[0]).toBeLessThan(loseContext.mock.invocationCallOrder[0])
  })
})
