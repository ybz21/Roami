import { useRef, type ClipboardEventHandler, type KeyboardEventHandler, type ReactNode } from 'react'
import { Input, Spin } from 'antd'
import { ArrowUp, StopIcon } from '../../icons'
import { useLayout } from '../../layout'
import './conversation.css'

type Action = { label: string; disabled?: boolean; pending?: boolean; icon?: ReactNode; force?: boolean; onClick: () => void }

type Props = {
  value: string; onChange: (value: string) => void; label: string; placeholder: string
  disabled?: boolean; maxLength?: number; id?: string; className?: string
  send: Action; stop?: Action; hasAttachments?: boolean
  leading?: ReactNode; settings?: ReactNode; voice?: ReactNode; attachments?: ReactNode
  header?: ReactNode; suggestions?: ReactNode; status?: ReactNode; options?: ReactNode
  onPaste?: ClipboardEventHandler<HTMLTextAreaElement>; onKeyDown?: KeyboardEventHandler<HTMLTextAreaElement>
}

export default function ConversationComposer({ value, onChange, label, placeholder, disabled, maxLength, id, className = '', send, stop, hasAttachments, leading, settings, voice, attachments, header, suggestions, status, options, onPaste, onKeyDown }: Props) {
  const { phone, landscape } = useLayout(), composing = useRef(false)
  const stopOnly = !!stop && !value.trim() && !hasAttachments
  const submit = () => { if (!disabled && !send.disabled && !send.pending && (value.trim() || hasAttachments)) send.onClick() }
  const keepKeyboard = (event: React.MouseEvent) => { if (phone) event.preventDefault() }
  return <form className={'tt-composer conversation-composer ' + className} onSubmit={event => { event.preventDefault(); submit() }}>
    {header}
    {attachments}
    <Input.TextArea id={id} variant="borderless" aria-label={label} placeholder={placeholder} value={value} disabled={disabled} maxLength={maxLength} autoSize={{ minRows: phone && landscape ? 1 : 2, maxRows: phone ? landscape ? 1 : 5 : 8 }} onChange={event => onChange(event.target.value)} onPaste={onPaste}
      onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false }}
      onKeyDown={event => {
        if (composing.current || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
        if (phone && event.key === 'Enter') return
        onKeyDown?.(event)
        if (!event.defaultPrevented && !phone && event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit() }
      }} />
    {suggestions}{status}
    {options && <div className="conversation-composer-options">{options}</div>}
    <div className="tt-cbar conversation-composer-bar"><div className="tt-cgrp conversation-composer-leading">{leading}</div><div className="conversation-composer-settings">{settings}</div><div className="tt-cend conversation-composer-end">
      {voice}
      {stop && !stopOnly && <button type="button" className="tt-pill ico" aria-label={stop.label} disabled={stop.disabled} onMouseDown={keepKeyboard} onClick={stop.onClick}><StopIcon size={14} /></button>}
      {stopOnly ? <button type="button" className={'tt-send stop' + (stop?.force ? ' force' : '')} aria-label={stop!.label} disabled={stop!.disabled} onMouseDown={keepKeyboard} onClick={stop!.onClick}><StopIcon size={14} /></button> : <button type="submit" className="tt-send" aria-label={send.label} aria-busy={send.pending || undefined} disabled={disabled || send.disabled || send.pending || (!value.trim() && !hasAttachments)} onMouseDown={keepKeyboard}>{send.pending ? <Spin size="small" /> : send.icon || <ArrowUp size={16} />}</button>}
    </div></div>
  </form>
}
