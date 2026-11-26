import type { Terminal } from '@xterm/xterm'

type Composition = {
  isComposing: boolean
  _isSendingComposition: boolean
  _compositionPosition: { start: number; end: number }
  compositionstart: () => void
  compositionend: () => void
  keydown: (event: KeyboardEvent) => boolean
  _handleAnyTextareaChanges: () => void
  updateCompositionElements: (dontRecurse?: boolean) => void
  _finalizeComposition: (wait: boolean) => void
}
type BrowserTerminal = {
  _compositionHelper: Composition
  _syncTextArea: () => void
  _inputEvent: (event: InputEvent) => boolean
  _keyPressHandled: boolean
  _unprocessedDeadKey: boolean
  coreService: { triggerDataEvent: (data: string, wasUserInput: boolean) => void }
  cancel: (event: Event) => void
}

export function clearTerminalInputContext(term: Terminal): void {
  const helper = (term as unknown as { _core: BrowserTerminal })._core._compositionHelper
  if (term.textarea && !helper.isComposing && !helper._isSendingComposition) term.textarea.value = ''
}

// xterm 5.5 compatibility; remove after upgrading with the IME fixes in xtermjs/xterm.js#5759 and #6060.
function synchronizeTerminalIME(term: Terminal): () => void {
  const core = (term as unknown as { _core: BrowserTerminal })._core
  const helper = core._compositionHelper
  const textarea = term.textarea
  if (!textarea || !helper || typeof core._syncTextArea !== 'function'
    || typeof core._inputEvent !== 'function' || typeof helper._finalizeComposition !== 'function'
    || typeof helper.keydown !== 'function' || typeof helper._handleAnyTextareaChanges !== 'function') {
    throw new Error('Unsupported xterm composition handler')
  }
  const start = helper.compositionstart
  const end = helper.compositionend
  const finalize = helper._finalizeComposition
  const input = core._inputEvent
  const keydown = helper.keydown
  const changes = helper._handleAnyTextareaChanges
  let imeInput = false
  let editableValue: string | undefined
  let beforeEdit: { value: string; inputType: string; tailSelectionStart: number | null } | undefined
  const resetEdit = () => {
    editableValue = undefined
    beforeEdit = undefined
  }
  const rememberInsert = (data: string, previous: string | undefined) => {
    const value = textarea.value
    if ((value === data || (previous !== undefined && value === previous + data)) && isTerminalEditText(value)) {
      editableValue = value
    }
  }
  const captureEdit = (event: InputEvent) => {
    const value = textarea.value
    const { selectionStart, selectionEnd } = textarea
    beforeEdit = value && value === editableValue ? {
      value,
      inputType: event.inputType,
      tailSelectionStart: selectionStart < selectionEnd && selectionEnd === value.length ? selectionStart : null,
    } : undefined
  }
  // Keystrokes and pastes outside the browser edit can move the remote cursor.
  const untrack = term.onData(resetEdit)
  textarea.addEventListener('beforeinput', captureEdit)
  textarea.addEventListener('blur', resetEdit)
  term.element?.addEventListener('pointerdown', resetEdit, true)
  helper.keydown = function (event) {
    imeInput = false
    return keydown.call(this, event)
  }
  helper._handleAnyTextareaChanges = function () {
    if (term.options.screenReaderMode) return changes.call(this)
    // IMEs can replace stale candidates with shorter punctuation; length is not a deletion signal.
    imeInput = true
  }
  helper._finalizeComposition = function (wait) {
    // The browser may replace the last candidate after compositionend, before Enter.
    if (!wait) this._compositionPosition.end = textarea.value.length
    finalize.call(this, wait)
  }
  helper.compositionstart = function () {
    imeInput = false
    resetEdit()
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
    const edit = beforeEdit?.inputType === event.inputType ? beforeEdit : undefined
    beforeEdit = undefined
    // insertText and the deferred finalizer can report the same IME commit.
    if (event.inputType === 'insertText' && (helper.isComposing || helper._isSendingComposition)) return false
    if (event.isComposing || helper.isComposing || helper._isSendingComposition || term.options.screenReaderMode) {
      return input.call(this, event)
    }
    const previous = edit?.value
    const current = textarea.value
    if (current !== editableValue) editableValue = undefined
    const selectedTail = event.inputType === 'insertText' && edit?.tailSelectionStart != null && event.data
      && current === edit.value.slice(0, edit.tailSelectionStart) + event.data
    if (previous && isTerminalEditText(current) && !this._keyPressHandled
      && (selectedTail || event.inputType === 'insertReplacementText'
        || (event.inputType === 'deleteContentBackward' && current.length <= previous.length))) {
      // The PTY can only edit text before its cursor. Replay the changed tail of the last forwarded draft.
      const data = terminalTailEdit(previous, current)
      if (data) this.coreService.triggerDataEvent(data, true)
      editableValue = current
      imeInput = false
      this._unprocessedDeadKey = false
      this.cancel(event)
      return true
    }
    if (imeInput) {
      const data = event.inputType === 'insertText' ? event.data
        : event.inputType === 'deleteContentBackward' ? '\x7f' : null
      if (data) {
        imeInput = false
        if (this._keyPressHandled) return false
        this._unprocessedDeadKey = false
        this.coreService.triggerDataEvent(data, true)
        if (event.inputType === 'insertText') rememberInsert(data, previous)
        this.cancel(event)
        return true
      }
    }
    const handled = input.call(this, event)
    if (handled && event.inputType === 'insertText' && event.data) rememberInsert(event.data, previous)
    return handled
  }
  return () => {
    untrack.dispose()
    textarea.removeEventListener('beforeinput', captureEdit)
    textarea.removeEventListener('blur', resetEdit)
    term.element?.removeEventListener('pointerdown', resetEdit, true)
    helper.compositionstart = start
    helper.compositionend = end
    helper._finalizeComposition = finalize
    core._inputEvent = input
    helper.keydown = keydown
    helper._handleAnyTextareaChanges = changes
  }
}

function isTerminalEditText(text: string): boolean {
  return !/[\x00-\x1f\x7f-\x9f]/.test(text)
}

function terminalTailEdit(previous: string, current: string): string {
  let prefix = 0
  for (const char of previous) {
    if (!current.startsWith(char, prefix)) break
    prefix += char.length
  }
  return '\x7f'.repeat(Array.from(previous.slice(prefix)).length) + current.slice(prefix)
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
