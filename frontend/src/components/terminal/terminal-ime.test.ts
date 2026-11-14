// @vitest-environment jsdom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Terminal } from '@xterm/xterm'
import { bindTerminalInput, clearTerminalDrop } from './terminal-ime'

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
    output = []
    release = bindTerminalInput(term, data => output.push(data))
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

  it('keeps the final candidate when Enter precedes the deferred finalizer', async () => {
    const textarea = term.textarea!
    textarea.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
    textarea.value = '合'
    textarea.dispatchEvent(new CompositionEvent('compositionupdate', { bubbles: true, data: '合并' }))
    textarea.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '合并' }))
    textarea.value = '合并'
    textarea.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter', keyCode: 13 }))
    await tick()
    expect(output.join('')).toBe('合并\r')
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

  it('forwards xterm commits and Enter when keydown ends an active composition', async () => {
    const textarea = term.textarea!
    textarea.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
    textarea.value = '合并'
    textarea.dispatchEvent(new CompositionEvent('compositionupdate', { bubbles: true, data: '合并' }))
    textarea.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter', keyCode: 13 }))
    textarea.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '合并' }))
    await tick()
    expect(output.join('')).toBe('合并\r')
  })

  it('preserves trailing input when normalizing an unselected pinyin commit', async () => {
    const textarea = term.textarea!
    compose(textarea, 's c p')
    textarea.value += '!'
    await tick()
    expect(output.join('')).toBe('scp!')
  })

  it('does not replace an unrelated keystroke after an empty pinyin commit', async () => {
    compose(term.textarea!, 's c p')
    term.textarea!.value = ''
    await tick()
    term.textarea!.dispatchEvent(new InputEvent('input', { bubbles: true, data: 'x', inputType: 'insertText' }))
    term.textarea!.dispatchEvent(new InputEvent('input', { bubbles: true, data: 's c p', inputType: 'insertText' }))
    expect(output.join('')).toBe('xs c p')
  })

  it('expires pinyin normalization when the composition emits no data', async () => {
    compose(term.textarea!, 's c p')
    term.textarea!.value = ''
    await tick()
    term.textarea!.dispatchEvent(new InputEvent('input', { bubbles: true, data: 's c p', inputType: 'insertText' }))
    expect(output.join('')).toBe('s c p')
  })

  it('keeps active and deferred compositions intact during a file drop', async () => {
    const textarea = term.textarea!
    textarea.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
    textarea.value = '合并'
    clearTerminalDrop(term)
    expect(textarea.value).toBe('合并')
    textarea.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '合并' }))
    clearTerminalDrop(term)
    await tick()
    expect(output.join('')).toBe('合并')
    textarea.value = '/tmp/dropped.txt'
    clearTerminalDrop(term)
    expect(textarea.value).toBe('')
  })
})
