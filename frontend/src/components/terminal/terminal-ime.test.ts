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

  const imeKey = (textarea: HTMLTextAreaElement, value: string, data: string | null, inputType = 'insertText') => {
    textarea.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Unidentified', keyCode: 229 }))
    textarea.value = value
    textarea.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, data, inputType }))
    textarea.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Unidentified', keyCode: 229 }))
  }

  it.each(['，', '。', '！', '？', ',', '.', '!', '?'])('inserts %s without deleting committed Chinese', async punctuation => {
    const textarea = term.textarea!
    compose(textarea, '完整文字')
    await tick()
    imeKey(textarea, punctuation, punctuation)
    await tick()
    expect(output.join('')).toBe('完整文字' + punctuation)
  })

  it('sends appended punctuation only once', async () => {
    const textarea = term.textarea!
    compose(textarea, '文字')
    await tick()
    imeKey(textarea, '文字，', '，')
    await tick()
    expect(output.join('')).toBe('文字，')
  })

  it('preserves repeated punctuation arriving before a timer tick', async () => {
    imeKey(term.textarea!, '！', '！')
    imeKey(term.textarea!, '！！', '！')
    await tick()
    expect(output.join('')).toBe('！！')
  })

  it('only deletes when the IME reports a backward deletion', async () => {
    const textarea = term.textarea!
    compose(textarea, '文字')
    await tick()
    imeKey(textarea, '文', null, 'deleteContentBackward')
    await tick()
    expect(output.join('')).toBe('文字\x7f')
  })

  it('does not infer deletion when an IME key clears stale textarea content', async () => {
    term.textarea!.value = '已发送的文字'
    term.textarea!.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, keyCode: 229 }))
    term.textarea!.value = ''
    await tick()
    expect(output).toEqual([])
  })

  it('does not replay punctuation after another composition starts', async () => {
    imeKey(term.textarea!, '，', '，')
    compose(term.textarea!, '继续')
    await tick()
    expect(output.join('')).toBe('，继续')
  })

  it('keeps a normal Backspace after an IME key that produces no input', async () => {
    term.textarea!.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, keyCode: 229 }))
    term.textarea!.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Backspace', keyCode: 8 }))
    await tick()
    expect(output.join('')).toBe('\x7f')
  })

  it('does not resend an IME punctuation key already handled by keypress', async () => {
    const textarea = term.textarea!
    textarea.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, keyCode: 229 }))
    textarea.dispatchEvent(new KeyboardEvent('keypress', { bubbles: true, charCode: 44 }))
    textarea.value = ','
    textarea.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, data: ',', inputType: 'insertText' }))
    await tick()
    expect(output.join('')).toBe(',')
  })

  it('keeps candidate edits local until composition ends', async () => {
    const textarea = term.textarea!
    textarea.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, keyCode: 229 }))
    textarea.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
    textarea.value = '文字'
    textarea.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, data: '文字', inputType: 'insertCompositionText', isComposing: true }))
    textarea.value = '文'
    textarea.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, inputType: 'deleteContentBackward', isComposing: true }))
    expect(output).toEqual([])
    textarea.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '文' }))
    await tick()
    expect(output.join('')).toBe('文')
  })

  it('keeps screen reader textarea handling unchanged', async () => {
    term.options.screenReaderMode = true
    imeKey(term.textarea!, '，', '，')
    await tick()
    expect(output.join('')).toBe('，')
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
