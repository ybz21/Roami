// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import OkrGoalMap from './OkrGoalMap'
import type { Observation, Workspace } from './okr-workspace'
vi.mock('../../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
afterEach(cleanup)
it('links methods only to their real KRs and retains unlinked methods separately', () => {
  const observation = (id: string, date: string, value: number): Observation => ({ id, date, value, metricId: 'visits', source: 'manual', sourceKey: 'manual:visits', note: '', capturedAt: date + 'T12:00:00Z' })
  const workspace: Workspace = {
    revision: 4, projectId: 'promotion', updatedAt: '2026-11-04T00:00:00Z',
    objective: 'Grow the community', startDate: '2026-11-01', endDate: '2026-11-30', autoCollect: false, swarm: '', reviews: [],
    metrics: [{ id: 'visits', name: 'Visits', unit: 'people', source: 'manual' }, { id: 'feedback', name: 'Feedback', unit: 'responses', source: 'manual' }],
    keyResults: [
      { id: 'reach', title: 'Reach people', metricId: 'visits', horizon: 'long', mode: 'increase', target: 100, dueDate: '2026-11-30' },
      { id: 'learn', title: 'Learn from feedback', metricId: 'feedback', horizon: 'short', mode: 'atLeast', target: 5, dueDate: '2026-11-30' },
    ],
    observations: [observation('before', '2026-10-31', 5), observation('start', '2026-11-01', 20), observation('latest', '2026-11-04', 45), { ...observation('other-source', '2026-11-05', 100), sourceKey: 'manual:old-visits' }],
    initiatives: [
      { id: 'video', title: 'Video examples', channel: 'Video', description: 'Record actual interactions', acceptance: '', keyResultIds: ['reach'] },
      { id: 'interview', title: 'Interview users', channel: 'Research', description: '', acceptance: '', keyResultIds: [] },
    ],
  }
  render(<OkrGoalMap workspace={workspace} />)
  const reach = screen.getByText('Reach people').closest('li')!, learn = screen.getByText('Learn from feedback').closest('li')!
  expect(within(reach).getByRole('progressbar', { name: 'Reach people' }).getAttribute('aria-valuenow')).toBe('25')
  expect(within(reach).getByText('25')).toBeTruthy()
  expect(within(learn).queryByRole('progressbar')).toBeNull()
  expect(within(learn).getByText('okr.target 5 responses')).toBeTruthy()
  expect(within(reach).getByText('Video examples')).toBeTruthy()
  expect(within(learn).queryByText('Video examples')).toBeNull()
  expect(screen.getByText('Interview users').closest('section')?.className).toBe('okr-map-unlinked')
  expect(screen.getByRole('heading', { name: 'Grow the community' })).toBeTruthy()
})
