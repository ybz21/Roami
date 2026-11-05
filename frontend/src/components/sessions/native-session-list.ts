import { createSessionPoll } from '../../session-poll'
import type { NativeSessionRecord } from './session-record'

export const useNativeSessionList = createSessionPoll<NativeSessionRecord[]>(
  '/agent/native-sessions', 5000, [], response => (response?.data || []).filter((session: NativeSessionRecord) => session.lifecycle !== 'closed'),
)

export const refreshSessionLists = () => window.dispatchEvent(new Event('roami:sessions-changed'))
