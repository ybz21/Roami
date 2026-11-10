import { useMemo } from 'react'
import { createSessionPoll } from '../../session-poll'
import type { NativeSessionRecord } from './session-record'

const useNativeRecords = createSessionPoll<NativeSessionRecord[]>(
  '/agent/native-sessions', 5000, [], response => Array.isArray(response?.data) ? response.data : [],
)

export function useNativeSessionList(enabled = true, includeClosed = false) {
  const snapshot = useNativeRecords(enabled)
  const value = useMemo(() => includeClosed ? snapshot.value : snapshot.value.filter(session => session.lifecycle !== 'closed' && session.lifecycle !== 'closing'), [snapshot.value, includeClosed])
  return { ...snapshot, value }
}

export const refreshSessionLists = () => window.dispatchEvent(new Event('roami:sessions-changed'))
