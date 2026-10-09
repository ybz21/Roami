// 设置页的「录一个快捷键」：点一下进入录制，按下组合键就存；Esc 取消；「重置」回默认
import { useEffect, useState } from 'react'
import { Button } from 'antd'
import { useI18n } from '../../i18n'
import { formatHotkey, hotkeyFromEvent, parseHotkey } from '../shell/keybindings'

export function HotkeyRecorder({ value, fallback, onChange, conflict }: { value: string; fallback: string; onChange: (v: string) => void; conflict?: string }) {
  const { t } = useI18n()
  const [rec, setRec] = useState(false)
  const [bad, setBad] = useState(false)
  useEffect(() => {
    if (!rec) return
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault(); e.stopPropagation()
      if (e.key === 'Escape') { setRec(false); return }
      const s = hotkeyFromEvent(e)
      if (!s) return // 只按了修饰键，等主键
      if (!parseHotkey(s)) { setBad(true); return } // 裸键不收
      setBad(false); setRec(false); onChange(s)
    }
    window.addEventListener('keydown', onKey, { capture: true })
    return () => window.removeEventListener('keydown', onKey, { capture: true } as any)
  }, [rec, onChange])
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
      <Button size="small" type={rec ? 'primary' : 'default'} onClick={() => { setRec(true); setBad(false) }}>
        {rec ? (bad ? t('set.hotkeyNeedMod') : t('set.hotkeyPress')) : <kbd style={{ fontFamily: 'var(--mono)' }}>{formatHotkey(value) || formatHotkey(fallback)}</kbd>}
      </Button>
      {value && value !== fallback && <Button size="small" type="text" onClick={() => onChange(fallback)}>{t('set.hotkeyReset')}</Button>}
      {conflict && <span style={{ color: 'var(--danger)', fontSize: 'var(--fs-meta)' }}>{t('set.hotkeyConflict', { name: conflict })}</span>}
    </span>
  )
}
