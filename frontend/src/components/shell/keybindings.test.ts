import { describe, it, expect } from 'vitest'
import { parseHotkey, matchHotkey, hotkeyFromEvent, formatHotkey, DEFAULT_KEYBINDINGS, resolveKeybindings, keybindingConflicts } from './keybindings'

const ev = (o: Partial<KeyboardEvent>) => ({ ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, code: '', key: '', ...o }) as KeyboardEvent

describe('语音快捷键', () => {
  it('默认 Mod+Shift+S：Ctrl 或 ⌘ 都算 Mod', () => {
    const h = parseHotkey(DEFAULT_KEYBINDINGS.voice)
    expect(matchHotkey(ev({ ctrlKey: true, shiftKey: true, code: 'KeyS' }), h)).toBe(true)
    expect(matchHotkey(ev({ metaKey: true, shiftKey: true, code: 'KeyS' }), h)).toBe(true)
    expect(matchHotkey(ev({ ctrlKey: true, code: 'KeyS' }), h)).toBe(false)
    expect(matchHotkey(ev({ ctrlKey: true, shiftKey: true, code: 'KeyV' }), h)).toBe(false)
  })
  it('显式 Ctrl 不认 ⌘；Alt 也能配', () => {
    const h = parseHotkey('Ctrl+Alt+KeyR')
    expect(matchHotkey(ev({ ctrlKey: true, altKey: true, code: 'KeyR' }), h)).toBe(true)
    expect(matchHotkey(ev({ metaKey: true, altKey: true, code: 'KeyR' }), h)).toBe(false)
  })
  it('裸键拒绝（会抢打字），F 键放行', () => {
    expect(parseHotkey('KeyS')).toBeNull()
    expect(parseHotkey('F8')).not.toBeNull()
    expect(parseHotkey('')).toBeNull()
    expect(parseHotkey('Ctrl+KeyA+KeyB')).toBeNull()
  })
  it('从按键事件生成偏好串；只按修饰键为空', () => {
    expect(hotkeyFromEvent(ev({ ctrlKey: true, shiftKey: true, code: 'KeyS', key: 's' }))).toBe('Ctrl+Shift+KeyS')
    expect(hotkeyFromEvent(ev({ ctrlKey: true, code: 'ControlLeft', key: 'Control' }))).toBe('')
  })
  it('显示成人看的样子', () => {
    expect(formatHotkey('Ctrl+Shift+KeyS')).toMatch(/S$/)
    expect(formatHotkey('Alt+Digit1')).toMatch(/1$/)
    expect(formatHotkey('nonsense')).toBe('')
  })
  it('覆盖叠在默认上，坏串当没改；同键冲突能查出来', () => {
    const kb = resolveKeybindings({ voice: 'Ctrl+Alt+KeyR', search: 'garbage', newTask: 'Mod+KeyW' })
    expect(kb.voice.spec).toBe('Ctrl+Alt+KeyR')
    expect(kb.search.spec).toBe(DEFAULT_KEYBINDINGS.search)
    const c = keybindingConflicts(kb)
    expect(c.newTask).toBe('closeTab')
    expect(c.closeTab).toBe('newTask')
    expect(c.voice).toBeUndefined()
  })
})
