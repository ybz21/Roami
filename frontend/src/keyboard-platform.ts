const currentPlatform = () => typeof navigator === 'undefined' ? '' : navigator.platform
export const isApplePlatform = (platform = currentPlatform()) => /Mac|iPhone|iPad/.test(platform)

type ShortcutModifiers = Pick<KeyboardEvent, 'ctrlKey' | 'metaKey'>

export function primaryShortcutLabel(platform = currentPlatform()): string {
  return isApplePlatform(platform) ? '⌘' : 'Ctrl+'
}

export function isPrimaryShortcut(e: ShortcutModifiers, platform = currentPlatform()): boolean {
  return isApplePlatform(platform) ? e.metaKey && !e.ctrlKey : e.ctrlKey || e.metaKey
}
