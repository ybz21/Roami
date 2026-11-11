// @vitest-environment jsdom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Terminal } from '@xterm/xterm'
import { synchronizeTerminalIME } from './terminal-ime'

const tick = () => new Promise(resolve => setTimeout(resolve, 5))

describe('xterm IME compatibility', () => {
  let TerminalClass: typeof import('@xterm/xterm').Terminal
  beforeAll(async () => {
    const canvas = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    TerminalClass = (await import('@xterm/xterm')).Terminal
    canvas.mockRestore()
  })
  let term: Terminal
  let host: HTMLDivElement
  let output: string[]
  let release: () => void
  beforeEach(async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {} }))
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    host = document.createElement('div')
    document.body.append(host)
    term = new TerminalClass({ cols: 80, rows: 24, allowProposedApi: true })
    term.open(host)
    release = synchronizeTerminalIME(term)
    output = []
    term.onData(data => output.push(data))
    await new Promise<void>(resolve => term.write('\x1b[20;7H', resolve))
  })
  afterEach(async () => {
    term?.textarea?.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '' }))
    await tick()
    release?.()
    term?.dispose()
    host?.remove()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })
  const compose = (textarea: HTMLTextAreaElement, text: string) => {
    textarea.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
    textarea.value = text
    textarea.dispatchEvent(new CompositionEvent('compositionupdate', { bubbles: true, data: text }))
    textarea.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: text }))
  }

  it('emits a commit once when insertText arrives before the deferred finalizer', async () => {
    const textarea = term.textarea!
    compose(textarea, '每一次')
    textarea.dispatchEvent(new InputEvent('input', { bubbles: true, data: '每一次', inputType: 'insertText' }))
    await tick()
    expect(output.join('')).toBe('每一次')
  })

  it('preserves two identical consecutive compositions without deduplicating user text', async () => {
    compose(term.textarea!, '一次')
    compose(term.textarea!, '一次')
    await tick()
    expect(output.join('')).toBe('一次一次')
  })

  it('flushes a commit before Enter even without an intervening render tick', async () => {
    compose(term.textarea!, '确认')
    term.textarea!.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter', keyCode: 13 }))
    await tick()
    expect(output.join('')).toBe('确认\r')
  })

  it('does not slice a whole-value replacement against an earlier composition', async () => {
    term.textarea!.value = 'previous text'
    compose(term.textarea!, '新的内容')
    await tick()
    expect(output.join('')).toBe('新的内容')
  })

  it('anchors the textarea immediately when composition starts', () => {
    const core = (term as unknown as { _core: { _renderService: { dimensions: { css: { cell: { width: number; height: number } } } } } })._core
    core._renderService.dimensions.css.cell.width = 8
    core._renderService.dimensions.css.cell.height = 16
    term.textarea!.style.left = '-9999em'
    term.textarea!.style.top = '0px'
    term.textarea!.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
    expect(term.textarea!.style.left).toBe('48px')
    expect(term.textarea!.style.top).toBe('304px')
  })

  it('keeps direct insertText input outside composition working', () => {
    term.textarea!.dispatchEvent(new InputEvent('input', { bubbles: true, data: 'a', inputType: 'insertText' }))
    expect(output.join('')).toBe('a')
  })
})
