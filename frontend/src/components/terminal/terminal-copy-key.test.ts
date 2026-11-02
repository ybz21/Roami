import { describe, expect, it } from 'vitest'
import { terminalCopyAction as copyAction } from './terminal-copy-key'
const terminalCopyAction = (e: Parameters<typeof copyAction>[0], selection: string) => copyAction(e, selection, true)

const key = { key: 'c', ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, repeat: false, isComposing: false }

describe('terminal copy and interrupt shortcuts', () => {
  it('interrupts with Command+C only without a selection', () => {
    expect(terminalCopyAction({ ...key, metaKey: true }, '')).toBe('interrupt')
    expect(terminalCopyAction({ ...key, metaKey: true }, 'selected text')).toBe('copy')
    expect(terminalCopyAction({ ...key, metaKey: true }, '  ')).toBe('copy')
  })
  it('keeps Command+Shift+C copy-only', () => {
    expect(terminalCopyAction({ ...key, key: 'C', metaKey: true, shiftKey: true }, '')).toBe('consume')
    expect(terminalCopyAction({ ...key, metaKey: true, shiftKey: true }, 'text')).toBe('copy')
  })
  it('does not turn holding Command+C into repeated interrupts', () => {
    expect(terminalCopyAction({ ...key, metaKey: true, repeat: true }, '')).toBe('consume')
  })
  it('preserves Control+C and Control+Shift+C', () => {
    expect(terminalCopyAction({ ...key, ctrlKey: true }, '')).toBe('pass')
    expect(terminalCopyAction({ ...key, ctrlKey: true }, 'text')).toBe('copy')
    expect(terminalCopyAction({ ...key, ctrlKey: true, shiftKey: true }, '')).toBe('consume')
  })
  it('leaves other modifiers and composition alone', () => {
    expect(terminalCopyAction({ ...key, metaKey: true, altKey: true }, '')).toBe('pass')
    expect(terminalCopyAction({ ...key, metaKey: true, ctrlKey: true }, '')).toBe('pass')
    expect(terminalCopyAction({ ...key, metaKey: true, isComposing: true }, '')).toBe('pass')
    expect(terminalCopyAction({ ...key, metaKey: true, key: 'v' }, '')).toBe('pass')
  })
  it('never maps the Windows Meta key to an interrupt', () => {
    expect(copyAction({ ...key, metaKey: true }, '', false)).toBe('consume')
    expect(copyAction({ ...key, ctrlKey: true }, '', false)).toBe('pass')
  })

})
