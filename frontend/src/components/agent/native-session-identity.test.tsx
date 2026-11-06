// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import NativeSession from './NativeSession'
const state = vi.hoisted(() => ({ metadata: {} as Record<string, unknown>, task: vi.fn() }))
vi.mock('./useAgentData', () => ({ useAgentData: () => ({ value: state.metadata, loading: false, failed: false, refresh: vi.fn() }) }))
vi.mock('./useAgentTask', () => ({ useAgentTask: state.task }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)
it.each(['taskId','nativeSessionId','projectId','conversationId','branchId','revision','lifecycle'])('does not mount a native conversation whose %s differs from its registered member', key => {
  state.task.mockReset()
  state.metadata = { nativeSessionId: 'native', taskId: 'task', projectId: 'project', conversationId: 'worker', branchId: 'branch', revision: 2, lifecycle: 'open', [key]: key === 'revision' ? 1 : 'foreign' }
  render(<NativeSession id="native" node={null} projects={[]} onChanged={vi.fn()} embedded expectedTask={{ id:'task', projectId:'project', conversationId:'worker', branchId:'branch', revision:2 }} />)
  expect(screen.getByRole('alert').textContent).toContain('swarm.member.sessionUnavailable')
  expect(state.task).not.toHaveBeenCalled()
})
