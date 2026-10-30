// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MobileSessionSwitch } from './MobileSessionSwitch'

vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../session-overview', () => ({ useSessionOverview: () => ({ value: [
  { name: 'recent', label: 'Recent session', running: false, waiting: false },
  { name: 'desktop', label: 'Desktop session', running: false, waiting: false },
] }) }))
afterEach(cleanup)

it('shows every shared open session in order, including the current one, without duplicating recent sessions', () => {
  render(<MobileSessionSwitch open active="phone" terms={['desktop', 'phone']} onClose={vi.fn()} onPick={vi.fn()} onAll={vi.fn()} />)
  const dialog = within(screen.getByRole('dialog'))
  expect(dialog.getAllByRole('button').map(button => button.textContent)).toEqual(['', 'Desktop sessionmobile.st.idle', 'phoneworkspace.current', 'Recent sessionmobile.st.idle', 'project.allSessions'])
  expect(dialog.getByRole('button', { name: /phone/ }).classList.contains('active')).toBe(true)
})
