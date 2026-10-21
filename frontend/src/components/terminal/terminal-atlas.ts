import type { WebglAddon } from '@xterm/addon-webgl'
import type { Terminal } from '@xterm/xterm'

type Atlas = {
  clearTexture: () => void
  onRemoveTextureAtlasCanvas: (listener: () => void) => { dispose: () => void }
}
type AtlasState = { revision: number; refresh: Set<() => void> }
type Renderer = {
  _charAtlas?: Atlas
  _clearModel: (glyphs: boolean) => void
  _glyphRenderer: { value?: { setAtlas: (atlas: Atlas) => void } }
  renderRows: (start: number, end: number) => void
}

const atlases = new WeakMap<Atlas, AtlasState>()

function trackAtlas(atlas: Atlas): AtlasState {
  const existing = atlases.get(atlas)
  if (existing) return existing
  const state: AtlasState = { revision: 0, refresh: new Set() }
  let pending = false
  const invalidate = () => {
    state.revision++
    if (pending) return
    pending = true
    // 分页合并尚在修改字形坐标，等本轮绘制结束再通知所有使用者。
    queueMicrotask(() => {
      pending = false
      for (const refresh of state.refresh) refresh()
    })
  }
  const clear = atlas.clearTexture
  atlas.clearTexture = function () {
    clear.call(this)
    invalidate()
  }
  atlas.onRemoveTextureAtlasCanvas(invalidate)
  atlases.set(atlas, state)
  return state
}

// xterm 5.5 / webgl 0.18 的兼容层：清空或合并共享图集后，每个 renderer 都要重建坐标和纹理。
// 上游修复：https://github.com/xtermjs/xterm.js/pull/6055（升级时移除此兼容层）。
export function synchronizeTerminalAtlas(term: Terminal, addon: WebglAddon): () => void {
  const renderer = (addon as unknown as { _renderer?: Renderer })._renderer
  if (!renderer || typeof renderer._clearModel !== 'function' || !renderer._glyphRenderer
    || typeof renderer.renderRows !== 'function') {
    throw new Error('Unsupported xterm WebGL renderer')
  }
  const renderRows = renderer.renderRows
  let current: AtlasState | undefined
  let revision = -1
  const refresh = () => term.refresh(0, term.rows - 1)
  renderer.renderRows = function (start, end) {
    const atlas = this._charAtlas
    if (atlas) {
      const next = trackAtlas(atlas)
      if (next !== current) {
        current?.refresh.delete(refresh)
        current = next
        current.refresh.add(refresh)
        revision = -1
      }
      if (revision !== current.revision) {
        revision = current.revision
        this._clearModel(true)
        // 合并后不同页面可能碰巧拥有相同 version，必须强制重新上传 GPU 纹理。
        this._glyphRenderer.value?.setAtlas(atlas)
        start = 0
        end = term.rows - 1
      }
    }
    renderRows.call(this, start, end)
  }
  return () => {
    current?.refresh.delete(refresh)
    renderer.renderRows = renderRows
  }
}
