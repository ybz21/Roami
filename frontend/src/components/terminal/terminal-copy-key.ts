import { isApplePlatform } from '../../keyboard-platform'

type CopyKey = Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'altKey' | 'repeat' | 'isComposing'>

export function terminalCopyAction(e: CopyKey, selection: string, apple = isApplePlatform()): 'copy' | 'interrupt' | 'consume' | 'pass' {
  if (e.isComposing || e.altKey || e.key.toLowerCase() !== 'c') return 'pass'
  const command = e.metaKey && !e.ctrlKey
  const control = e.ctrlKey && !e.metaKey
  if (!command && !control) return 'pass'
  if (selection.length > 0) return 'copy'
  if (command && !e.shiftKey) return apple && !e.repeat ? 'interrupt' : 'consume'
  return e.shiftKey ? 'consume' : 'pass'
}
