// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import OkrReviewEvidence from './OkrReviewEvidence'
import type { Workspace } from './okr-workspace'
const api = vi.hoisted(() => vi.fn())
vi.mock('../../../api', () => ({ api }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string, vars?: object) => key + (vars ? JSON.stringify(vars) : '') }) }))
const snapshot: Workspace = {
  projectId: 'project', revision: 3, objective: 'Original objective', startDate: '2026-11-01', endDate: '2026-11-30', swarm: 'team', autoCollect: false,
  metrics: [{ id: 'stars', name: 'Original stars', unit: '', source: 'github', repo: 'owner/original', field: 'stars', sourceKey: 'github:42:stars' }],
  keyResults: [{ id: 'kr', title: 'Original result', horizon: 'long', metricId: 'stars', target: 100, mode: 'increase', dueDate: '2026-11-30' }],
  observations: [{ id: 'observation', metricId: 'stars', value: 12, source: 'github', sourceKey: 'github:42:stars', date: '2026-11-01', capturedAt: '2026-11-01T00:00:00.000000000Z', note: 'Original evidence note' }], reviews: [], updatedAt: '2026-11-01T00:00:00Z',
}
beforeEach(() => { api.mockReset(); api.mockResolvedValue({ data: snapshot }) })
afterEach(cleanup)
function expand() {
  const details = screen.getByText('okr.viewEvidence').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  return details
}
it('loads the review-specific server snapshot on demand and reuses it after reopening', async () => {
  render(<OkrReviewEvidence projectId="project" reviewId="review-id" />)
  expect(api).not.toHaveBeenCalled()
  const details = expand()
  expect(await screen.findByText('Original objective')).toBeTruthy()
  expect(screen.getByText('Original evidence note')).toBeTruthy()
  expect(screen.getAllByText('github:42:stars').length).toBe(2)
  expect(api).toHaveBeenCalledWith('GET', '/projects/project/okr/reviews/review-id/evidence', undefined, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  details.open = false; fireEvent(details, new Event('toggle'))
  details.open = true; fireEvent(details, new Event('toggle'))
  expect(api).toHaveBeenCalledTimes(1)
})
it('keeps the evidence disclosure available after a failure and retries only on request', async () => {
  api.mockRejectedValueOnce(new Error('OKR_UNAVAILABLE'))
  render(<OkrReviewEvidence projectId="project" reviewId="review-id" />)
  expand()
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'inbox.retry' }))
  expect(await screen.findByText('Original objective')).toBeTruthy()
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(api).toHaveBeenCalledTimes(2)
})
