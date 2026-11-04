// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import OkrGoalMap from './OkrGoalMap'
import type { Workspace } from './okr-workspace'
vi.mock('../../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)
it('links methods only to their real KRs and retains unlinked methods separately', () => {
  const workspace = { objective: 'Grow the community', metrics: [], keyResults: [{ id: 'reach', title: 'Reach people', target: 100 }, { id: 'learn', title: 'Learn from feedback', target: 5 }], initiatives: [{ id: 'video', title: 'Video examples', channel: 'Video', description: 'Record actual interactions', keyResultIds: ['reach'] }, { id: 'interview', title: 'Interview users', channel: 'Research', description: '', keyResultIds: [] }] } as unknown as Workspace
  render(<OkrGoalMap workspace={workspace} />)
  const reach = screen.getByText('Reach people').closest('li')!, learn = screen.getByText('Learn from feedback').closest('li')!
  expect(within(reach).getByText('Video examples')).toBeTruthy()
  expect(within(learn).queryByText('Video examples')).toBeNull()
  expect(screen.getByText('Interview users').closest('section')?.className).toBe('okr-map-unlinked')
  expect(screen.getByRole('heading', { name: 'Grow the community' })).toBeTruthy()
})
