// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { notificationDestination } from './notification-destination'
import type { AgentNotice } from './agent-protocol'
const state = vi.hoisted(() => ({ teams: vi.fn(), api: vi.fn() }))
vi.mock('../../api', () => ({ api: state.api }))
vi.mock('../swarm/swarm-directory', () => ({ loadSwarmDirectory: state.teams }))
const notice = { conversation_id: 'project-main', branch_id: 'branch', message_id: 'message' } as AgentNotice
const team = { id: 'sw-bound', mainConversationId: 'project-main', target: { projectId: 'project' } }
beforeEach(() => { vi.clearAllMocks(); history.replaceState({}, '', '#/home/notifications/home?node=remote'); state.teams.mockResolvedValue([team]); state.api.mockResolvedValue({ data: { projectId: 'project', swarm: 'sw-bound' } }) })
it('keeps Home references in Home without any project discovery', async () => {
  expect(await notificationDestination(notice, 'project-main')).toBeNull()
  expect(state.teams).not.toHaveBeenCalled()
})
it('routes only a verified project Main to its exact project and message, preserving the node', async () => {
  const destination = await notificationDestination(notice, 'home')
  expect(destination).toBe('#/okr/project?node=remote&okrConversation=project-main&okrBranch=branch&okrMessage=message')
  expect(location.hash).toBe('#/home/notifications/home?node=remote')
  expect(state.api).toHaveBeenCalledWith('GET', '/projects/project/okr')
})
it('rejects cross-project ambiguity instead of guessing from names', async () => {
  state.teams.mockResolvedValue([team, { ...team, target: { projectId: 'other' } }])
  await expect(notificationDestination(notice, 'home')).rejects.toThrow('Ambiguous')
  expect(state.api).not.toHaveBeenCalled()
})
it.each([{ projectId: 'project', swarm: 'different' }, { projectId: 'other', swarm: 'sw-bound' }])('does not bind an unconfirmed team from stale metadata', async workspace => {
  state.api.mockResolvedValue({ data: workspace })
  expect(await notificationDestination(notice, 'home')).toBeNull()
})
