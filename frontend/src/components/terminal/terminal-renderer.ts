import type { WebglAddon } from '@xterm/addon-webgl'

type CreateRenderer = (onLost: () => void) => () => void

// Keep terminal buffers and connections alive while releasing hidden GPU renderers.
export function createTerminalRenderer(create: CreateRenderer, refresh: () => void) {
  let active = false
  let disposed = false
  let generation = 0
  let release: (() => void) | undefined
  const drop = () => {
    generation++
    const previous = release
    release = undefined
    try { previous?.() } catch { /* DOM renderer remains available. */ }
  }
  const mount = () => {
    if (!active || disposed || release) return
    const current = ++generation
    try {
      const cleanup = create(() => {
        if (generation !== current || disposed) return
        drop()
        refresh()
      })
      if (generation !== current || disposed) cleanup()
      else release = cleanup
    } catch { /* Keep the DOM renderer when GPU allocation fails. */ }
  }
  return {
    setActive(next: boolean) {
      if (disposed) return
      active = next
      if (active) mount()
      else drop()
    },
    rebuild() { drop(); mount() },
    dispose() { disposed = true; drop() },
  }
}

export function disposeTerminalWebgl(addon: WebglAddon) {
  // xterm 0.18 removes the canvas but leaves context reclamation to browser GC.
  const gl = (addon as unknown as { _renderer?: { _gl?: WebGL2RenderingContext } })._renderer?._gl
  try { addon.dispose() } finally {
    try { gl?.getExtension('WEBGL_lose_context')?.loseContext() } catch { /* Already lost. */ }
  }
}
