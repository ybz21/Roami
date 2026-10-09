// 全站快捷键：每个动作一条偏好，存成 'Mod+Shift+KeyS' 这种串（修饰键 + KeyboardEvent.code），
// 按 code 匹配不看布局。Mod = Mac 上 ⌘、其它 Ctrl；显式写 Ctrl / Meta 就只认那一个。
// 都能在 设置 › 界面 › 快捷键 里改：本机别的软件占了哪个键，换一个就是，不用改代码。
import { useMemo } from 'react'
import { usePreferences } from '../../preferences'

export const KEY_ACTIONS = ['search', 'newTask', 'newTerminal', 'closeTab', 'toggleInspector', 'focus', 'searchContent', 'panelFiles', 'panelGit', 'voice'] as const
export type KeyAction = typeof KEY_ACTIONS[number]
export const DEFAULT_KEYBINDINGS: Record<KeyAction, string> = {
  search: 'Mod+KeyK',
  newTask: 'Mod+KeyN',
  newTerminal: 'Mod+KeyT',
  closeTab: 'Mod+KeyW',
  toggleInspector: 'Mod+KeyJ',
  focus: 'Mod+Shift+KeyJ',
  searchContent: 'Mod+Shift+KeyF',
  panelFiles: 'Mod+Shift+KeyE',
  panelGit: 'Mod+Shift+KeyG',
  voice: 'Mod+Shift+KeyS',
}

export type Hotkey = { mod: boolean; ctrl: boolean; meta: boolean; alt: boolean; shift: boolean; code: string }

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '')

export function parseHotkey(s: string | undefined | null): Hotkey | null {
  const parts = String(s || '').split('+').map((p) => p.trim()).filter(Boolean)
  const h: Hotkey = { mod: false, ctrl: false, meta: false, alt: false, shift: false, code: '' }
  for (const p of parts) {
    const k = p.toLowerCase()
    if (k === 'mod' || k === 'cmdorctrl') h.mod = true
    else if (k === 'ctrl' || k === 'control') h.ctrl = true
    else if (k === 'meta' || k === 'cmd' || k === 'command' || k === 'super') h.meta = true
    else if (k === 'alt' || k === 'option') h.alt = true
    else if (k === 'shift') h.shift = true
    else if (!h.code) h.code = p
    else return null
  }
  if (!h.code) return null
  // 没有修饰键的普通键会抢走打字：只放行 F 键
  if (!h.mod && !h.ctrl && !h.meta && !h.alt && !/^F\d{1,2}$/.test(h.code)) return null
  return h
}

export function matchHotkey(e: KeyboardEvent, h: Hotkey | null): boolean {
  if (!h || e.code !== h.code) return false
  if (h.mod) { if (!(e.ctrlKey || e.metaKey)) return false }
  else { if (e.ctrlKey !== h.ctrl || e.metaKey !== h.meta) return false }
  return e.altKey === h.alt && e.shiftKey === h.shift
}

/** keyup 时「组合里的任一键松开」都算一次松开——S 先松或修饰键先松都是 */
export function isHotkeyKeyUp(e: KeyboardEvent, h: Hotkey | null): boolean {
  if (!h) return false
  return e.code === h.code || e.key === 'Shift' || e.key === 'Control' || e.key === 'Meta' || e.key === 'Alt'
}

/** 从一次 keydown 生成偏好串；只按了修饰键返回空 */
export function hotkeyFromEvent(e: KeyboardEvent): string {
  if (['Shift', 'Control', 'Meta', 'Alt'].includes(e.key) || !e.code) return ''
  const parts: string[] = []
  if (e.ctrlKey) parts.push('Ctrl')
  if (e.metaKey) parts.push('Meta')
  if (e.altKey) parts.push('Alt')
  if (e.shiftKey) parts.push('Shift')
  parts.push(e.code)
  return parts.join('+')
}

function keyLabel(code: string): string {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3)
  if (/^Digit\d$/.test(code)) return code.slice(5)
  if (code === 'Space') return 'Space'
  return code.replace(/^Arrow/, '')
}

export function formatHotkey(s: string | undefined | null): string {
  const h = parseHotkey(s)
  if (!h) return ''
  const parts: string[] = []
  if (h.mod) parts.push(isMac ? '⌘' : 'Ctrl')
  if (h.ctrl) parts.push(isMac ? '⌃' : 'Ctrl')
  if (h.meta) parts.push(isMac ? '⌘' : 'Win')
  if (h.alt) parts.push(isMac ? '⌥' : 'Alt')
  if (h.shift) parts.push(isMac ? '⇧' : 'Shift')
  parts.push(keyLabel(h.code))
  return isMac ? parts.join('') : parts.join('+')
}

export type Keybindings = Record<KeyAction, { spec: string; key: Hotkey | null; label: string }>

/** 偏好里的覆盖叠在默认值上；存坏了的串当没改 */
export function resolveKeybindings(overrides: Partial<Record<string, string>> | undefined): Keybindings {
  const out = {} as Keybindings
  for (const a of KEY_ACTIONS) {
    const o = overrides?.[a]
    const spec = o && parseHotkey(o) ? o : DEFAULT_KEYBINDINGS[a]
    out[a] = { spec, key: parseHotkey(spec), label: formatHotkey(spec) }
  }
  return out
}

/** 两个动作绑到同一个键：返回 动作 → 和它撞的另一个动作 */
export function keybindingConflicts(kb: Keybindings): Partial<Record<KeyAction, KeyAction>> {
  const out: Partial<Record<KeyAction, KeyAction>> = {}
  for (const a of KEY_ACTIONS) for (const b of KEY_ACTIONS) if (a !== b && kb[a].spec === kb[b].spec) { out[a] = b; break }
  return out
}

export function useKeybindings(): Keybindings {
  const [prefs] = usePreferences()
  return useMemo(() => resolveKeybindings(prefs.keybindings), [prefs.keybindings])
}
