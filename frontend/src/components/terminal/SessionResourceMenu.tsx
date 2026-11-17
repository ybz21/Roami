import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Dropdown } from 'antd'
import { useI18n } from '../../i18n'
import { CheckIcon, ChevronDown, CloseIcon } from '../../icons'
import { FileTypeIcon } from '../files/file-icons'
import type { FileTab } from './term-tabs-store'
import './session-resources.css'

export default function SessionResourceMenu({ session, label, icon, sessionViewLabel, files, active, activeFile, dirtyFiles, sessionButton, onSession, onFile, onCloseFile }: {
  session: string
  label: string
  icon: ReactNode
  sessionViewLabel?: string
  files: FileTab[]
  active: boolean
  activeFile: string
  dirtyFiles: ReadonlySet<string>
  sessionButton: RefObject<HTMLButtonElement>
  onSession: () => void
  onFile: (path: string) => void
  onCloseFile: (path: string) => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const menuId = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  useEffect(() => { setOpen(false) }, [session])
  useEffect(() => {
    if (!files.length && open) { setOpen(false); sessionButton.current?.focus() }
  }, [files.length, open, sessionButton])
  useEffect(() => {
    if (!open) return
    const frame = requestAnimationFrame(() => popup.current?.querySelector<HTMLElement>('.ant-dropdown-menu-item-selected')?.focus())
    return () => cancelAnimationFrame(frame)
  }, [open])
  if (!files.length) return null
  const nameOf = (path: string) => path.split('/').pop() || path
  const selected = active ? (activeFile ? `file:${activeFile}` : 'session') : ''
  return <Dropdown trigger={['click']} placement="bottomLeft" align={{ overflow: { adjustX: true, adjustY: true, shiftX: true } }} autoFocus open={open}
    onOpenChange={setOpen} overlayClassName="tt-session-resource-popup"
    popupRender={content => <div ref={popup} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setOpen(false); trigger.current?.focus() }
      if (event.key === 'Tab') setOpen(false)
    }}>{content}</div>}
    menu={{ id: menuId, selectedKeys: selected ? [selected] : [], items: [
      { key: 'session', ...{ role: 'menuitemradio', 'aria-checked': selected === 'session' }, icon: <span className="tt-session-resource-icon">{icon}</span>, label: <span className="tt-session-resource-row"><span className="nm">{sessionViewLabel || t('tabs.conversation')}</span>{selected === 'session' && <CheckIcon />}</span>, onClick: onSession },
      { type: 'divider' },
      { type: 'group', label: t('tabs.openedFiles'), children: files.map(file => {
        const name = nameOf(file.path)
        const text = files.some(other => other.path !== file.path && nameOf(other.path) === name) ? file.path : name
        return { key: `file:${file.path}`, ...{ role: 'menuitemradio', 'aria-checked': selected === `file:${file.path}` }, icon: <span className="tt-session-resource-icon"><FileTypeIcon name={name} /></span>,
          label: <span className="tt-session-resource-row" title={file.path}>
            <span className="nm">{text}</span>
            {dirtyFiles.has(file.path) && <span className="tt-tab-dirty" role="img" aria-label={t('file.unsaved')} />}
            {selected === `file:${file.path}` && <CheckIcon />}
            <button type="button" className="tt-act ico" aria-label={t('tabs.closeFile', { name })} onClick={event => { event.stopPropagation(); onCloseFile(file.path) }}><CloseIcon /></button>
          </span>, onClick: () => onFile(file.path) }
      }) },
    ], onClick: () => { setOpen(false); trigger.current?.focus() } }}>
    <button ref={trigger} type="button" className="tt-session-resource-trigger" aria-label={t('tabs.sessionResources', { name: label })}
      aria-haspopup="menu" aria-expanded={open} aria-controls={menuId} onClick={event => event.stopPropagation()}
      onKeyDown={event => { if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true) } }}><ChevronDown size={13} /></button>
  </Dropdown>
}
