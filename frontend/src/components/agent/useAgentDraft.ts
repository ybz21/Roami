import { useMemo, useState } from 'react'

function readDraft(key: string) {
  try { return localStorage.getItem(key) || '' } catch { return '' }
}

export function useAgentDraft(key: string) {
  const stored = useMemo(() => readDraft(key), [key])
  const [edit, setEdit] = useState({ key, text: stored })
  const text = edit.key === key ? edit.text : stored
  const setText = (value: string, destination = key) => setEdit({ key: destination, text: value })
  return [text, setText] as const
}
