import type { Terminal } from '@xterm/xterm'

type Composition = {
  isComposing: boolean
  _isSendingComposition: boolean
  _compositionPosition: { start: number; end: number }
  compositionstart: () => void
  compositionend: () => void
  updateCompositionElements: (dontRecurse?: boolean) => void
  _finalizeComposition: (wait: boolean) => void
}
type BrowserTerminal = {
  _compositionHelper: Composition
  _syncTextArea: () => void
  _inputEvent: (event: InputEvent) => boolean
}

export function clearTerminalDrop(term: Terminal): void {
  const helper = (term as unknown as { _core: BrowserTerminal })._core._compositionHelper
  if (term.textarea && !helper.isComposing && !helper._isSendingComposition) term.textarea.value = ''
}

// xterm 5.5 compatibility; remove after upgrading with the IME fixes in xtermjs/xterm.js#5759 and #6060.
export function synchronizeTerminalIME(term: Terminal): () => void {
  const core = (term as unknown as { _core: BrowserTerminal })._core
  const helper = core._compositionHelper
  const textarea = term.textarea
  if (!textarea || !helper || typeof core._syncTextArea !== 'function'
    || typeof core._inputEvent !== 'function' || typeof helper._finalizeComposition !== 'function') {
    throw new Error('Unsupported xterm composition handler')
  }
  const start = helper.compositionstart
  const end = helper.compositionend
  const finalize = helper._finalizeComposition
  const input = core._inputEvent
  helper._finalizeComposition = function (wait) {
    // The browser may replace the last candidate after compositionend, before Enter.
    if (!wait) this._compositionPosition.end = textarea.value.length
    finalize.call(this, wait)
  }
  helper.compositionstart = function () {
    // A new composition must not cancel the preceding deferred commit.
    if (this._isSendingComposition) this._finalizeComposition(false)
    core._syncTextArea()
    if (!term.options.screenReaderMode) textarea.value = ''
    start.call(this)
    this.updateCompositionElements(true)
  }
  helper.compositionend = function () {
    // Enter or another composition can arrive before compositionupdate's timer.
    this._compositionPosition.end = textarea.value.length
    end.call(this)
  }
  core._inputEvent = function (event) {
    // insertText and the deferred finalizer can report the same IME commit.
    if (event.inputType === 'insertText' && (helper.isComposing || helper._isSendingComposition)) return false
    return input.call(this, event)
  }
  return () => {
    helper.compositionstart = start
    helper.compositionend = end
    helper._finalizeComposition = finalize
    core._inputEvent = input
  }
}

export function bindTerminalInput(term: Terminal, send: (data: string) => void): () => void {
  const releaseIME = synchronizeTerminalIME(term)
  const textarea = term.textarea!
  let pendingPinyin: string | null = null
  let pendingTimer: ReturnType<typeof setTimeout> | undefined
  const onStart = () => {
    clearTimeout(pendingTimer)
    pendingPinyin = null
  }
  const onEnd = (event: CompositionEvent) => {
    // macOS can commit unselected pinyin with spaces when switching input methods.
    pendingPinyin = /^[a-zA-Z][a-zA-Z ]*$/.test(event.data) ? event.data : null
    clearTimeout(pendingTimer)
    // xterm's finalizer is already queued; an empty commit must not affect later input.
    pendingTimer = setTimeout(() => { pendingPinyin = null }, 0)
  }
  textarea.addEventListener('compositionstart', onStart)
  textarea.addEventListener('compositionend', onEnd)
  const subscription = term.onData(data => {
    const pinyin = pendingPinyin
    pendingPinyin = null
    if (pinyin && data.startsWith(pinyin)) {
      send(pinyin.replace(/ /g, '') + data.slice(pinyin.length))
    } else {
      send(data)
    }
  })
  return () => {
    clearTimeout(pendingTimer)
    textarea.removeEventListener('compositionstart', onStart)
    textarea.removeEventListener('compositionend', onEnd)
    subscription.dispose()
    releaseIME()
  }
}
