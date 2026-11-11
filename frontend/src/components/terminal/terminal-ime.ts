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
  const input = core._inputEvent
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
    core._inputEvent = input
  }
}
