import { describe, expect, it } from 'vitest'
import { isPrimaryShortcut, primaryShortcutLabel } from './keyboard-platform'

describe('platform shortcut modifiers', () => {
  it('shows Command on Apple devices and Control elsewhere', () => {
    for (const platform of ['MacIntel', 'iPhone', 'iPad']) expect(primaryShortcutLabel(platform)).toBe('⌘')
    for (const platform of ['Win32', 'Linux x86_64', '']) expect(primaryShortcutLabel(platform)).toBe('Ctrl+')
  })
  it('does not steal Mac Control shortcuts from terminal programs', () => {
    expect(isPrimaryShortcut({ ctrlKey: true, metaKey: false }, 'MacIntel')).toBe(false)
    expect(isPrimaryShortcut({ ctrlKey: false, metaKey: true }, 'MacIntel')).toBe(true)
    expect(isPrimaryShortcut({ ctrlKey: true, metaKey: true }, 'MacIntel')).toBe(false)
  })
  it('preserves existing Control shortcuts on Windows and Linux', () => {
    for (const platform of ['Win32', 'Linux x86_64']) {
      expect(isPrimaryShortcut({ ctrlKey: true, metaKey: false }, platform)).toBe(true)
      expect(isPrimaryShortcut({ ctrlKey: false, metaKey: false }, platform)).toBe(false)
    }
  })
})
