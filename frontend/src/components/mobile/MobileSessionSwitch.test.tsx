// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MobileSessionSwitch } from './MobileSessionSwitch'

const native = vi.hoisted(() => ({ value: [] as any[] }))
vi.mock('../sessions/native-session-list', () => ({ useNativeSessionList: () => native }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../session-overview', () => ({ useSessionOverview: () => ({ value: [
  { name: 'recent', label: 'Recent session', running: false, waiting: false },
  { name: 'desktop', label: 'Desktop session', running: false, waiting: false },
] }) }))
afterEach(() => { cleanup(); native.value = [] })

it('shows every shared open session in order, including the current one, without duplicating recent sessions', () => {
  render(<MobileSessionSwitch open active="phone" terms={['desktop', 'phone']} onClose={vi.fn()} onPick={vi.fn()} onAll={vi.fn()} />)
  const dialog = within(screen.getByRole('dialog'))
  expect(dialog.getAllByRole('button').map(button => button.textContent)).toEqual(['', 'Desktop sessionmobile.st.idle', 'phoneworkspace.current', 'Recent sessionmobile.st.idle', 'project.allSessions'])
  expect(dialog.getByRole('button', { name: /phone/ }).classList.contains('active')).toBe(true)
})


it('mixes Roami and Codex sessions in the same switcher rows and preserves their handles', async () => {
  native.value = [{ nativeSessionId: 'native-one', taskId: 'task-one', title: 'Roami chat', taskState: 'waiting_user', lastActivity: 50 }]
  const pick = vi.fn()
  render(<MobileSessionSwitch open active="roami:native-one" terms={['desktop', 'roami:native-one']} onClose={vi.fn()} onPick={pick} onAll={vi.fn()} />)
  const row = screen.getByRole('button', { name: /Roami chat/ })
  expect(row.className).toBe(screen.getByRole('button', { name: /Desktop session/ }).className + ' active')
  expect(screen.getAllByText('Roami chat')).toHaveLength(1)
})
