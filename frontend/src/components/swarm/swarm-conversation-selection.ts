import { useLayoutEffect, useState } from 'react'

type Selection = { key: string; recipient: string }
const handledMainRequests = new Map<string, string>()

function readSelection(key: string): Selection {
  try {
    const recipient = localStorage.getItem(key)
    if (recipient) return { key, recipient }
  } catch { /* Keep the conversation usable without persisted preferences. */ }
  return { key, recipient: 'main' }
}

function rememberSelection(value: Selection) {
  try { localStorage.setItem(value.key, value.recipient) } catch { /* Retain the visible selection. */ }
}

export function useSwarmConversationSelection(key: string, mainRequest?: string) {
  const [stored, setStored] = useState(() => readSelection(key))
  const current = stored.key === key ? stored : readSelection(key)
  const forceMain = Boolean(mainRequest && handledMainRequests.get(key) !== mainRequest)
  const value = forceMain ? { key, recipient: 'main' } : current

  useLayoutEffect(() => {
    if (mainRequest) handledMainRequests.set(key, mainRequest)
    if (value !== stored) setStored(value)
    rememberSelection(value)
  }, [key, mainRequest, stored, value])

  const select = (recipient: string) => {
    const next = { key, recipient }
    rememberSelection(next)
    setStored(next)
  }
  return [value.recipient, select] as const
}
