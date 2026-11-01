// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { agentReadiness, nextOnboardingStep, onboardingChanged, useOnboardingState } from './onboarding-state'

const fixture = vi.hoisted(() => ({ node: 'a', loaded: true, prefs: {} as any, api: vi.fn(), agents: vi.fn(), save: vi.fn() }))
vi.mock('../../api', () => ({ api: (...args: any[]) => fixture.api(...args) }))
vi.mock('../../agent-registry', () => ({ discoverAgents: () => fixture.agents() }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => fixture.node, nodeApi: (path: string) => fixture.node + path }))
vi.mock('../../preferences', () => ({ usePreferences: () => [fixture.prefs, fixture.save], getPreferences: () => fixture.prefs, preferencesLoaded: () => fixture.loaded }))
const model = (name = '') => ({ main: { model: name, baseUrl: name ? 'https://example.test/v1' : '', keyConfigured: false }, worker: { model: name }, verified: false })
let models: any, projects: any[], catalog: any
beforeEach(() => {
  fixture.node = 'a'; fixture.loaded = true; fixture.prefs = {}; models = model(); projects = []; catalog = { sources: [], models: [] }
  fixture.save.mockReset().mockResolvedValue(true); fixture.agents.mockReset().mockResolvedValue([])
  fixture.api.mockReset().mockImplementation(async (_method, path) => ({ data: path === '/projects' ? { projects } : path === '/agent/model-gateway/catalog' ? catalog : models }))
  onboardingChanged()
})
afterEach(cleanup)
it('shares initial requests and waits for all facts and preferences before showing a new installation', async () => {
  fixture.loaded = false
  const first = renderHook(() => useOnboardingState()), second = renderHook(() => useOnboardingState())
  expect(first.result.current.visible).toBe(false)
  await waitFor(() => expect(second.result.current.loading).toBe(false))
  expect(fixture.api).toHaveBeenCalledTimes(3); expect(fixture.agents).toHaveBeenCalledTimes(1)
  expect(first.result.current.visible).toBe(false)
  fixture.loaded = true; first.rerender()
  expect(first.result.current.visible).toBe(true)
  await act(async () => { await first.result.current.change({ started: true }) })
  expect(fixture.save).toHaveBeenCalledWith({ onboarding: { a: { started: true } } })
})
it('does not interrupt existing users or misclassify a failed read as an empty installation', async () => {
  models = model('existing')
  const state = renderHook(() => useOnboardingState())
  await waitFor(() => expect(state.result.current.loading).toBe(false))
  expect(state.result.current.visible).toBe(false)
  fixture.prefs = { onboarding: { a: { started: true } } }; state.rerender()
  expect(state.result.current.visible).toBe(true)
  fixture.api.mockRejectedValue(new Error('offline'))
  act(() => state.result.current.refresh())
  await waitFor(() => expect(state.result.current.failed).toBe(true))
  expect(state.result.current.value?.models.main.model).toBe('existing')
})
it('ignores a late response after changing nodes', async () => {
  let finish: (value: any) => void
  fixture.api.mockImplementation((_method, path) => path === '/projects' ? Promise.resolve({ data: { projects: [] } }) : path === '/agent/model-gateway/catalog' ? Promise.resolve({ data: catalog }) : fixture.node === 'a' ? new Promise(resolve => { finish = resolve }) : Promise.resolve({ data: model('node-b') }))
  const state = renderHook(() => useOnboardingState())
  fixture.node = 'b'; state.rerender()
  await waitFor(() => expect(state.result.current.value?.models.main.model).toBe('node-b'))
  await act(async () => { finish!({ data: model('late-node-a') }) })
  expect(state.result.current.value?.models.main.model).toBe('node-b')
})
it('requires call evidence rather than a catalog, binary, or preset before completing setup steps', () => {
  const snapshot: any = { catalog: { sources: [{ id: 'source' }], models: [] }, models: model('configured'), agents: [{ kind: 'codex', installed: true, modelPreset: 'existing' }], projects: [] }
  expect(nextOnboardingStep(snapshot, {})).toBe('model')
  snapshot.catalog.models.push({ id: 'saved-model' })
  expect(nextOnboardingStep(snapshot, {})).toBe('agents')
  snapshot.models.verified = true
  expect(nextOnboardingStep(snapshot, {})).toBe('agents')
  expect(agentReadiness(snapshot.agents[0])).toBe('pending')
  snapshot.agents[0].verified = true
  expect(nextOnboardingStep(snapshot, {})).toBe('project')
  snapshot.projects.push({ key: 'project' })
  expect(nextOnboardingStep(snapshot, {})).toBe('task')
})

it('recognizes saved model connections without interrupting existing users', async () => {
  catalog = { sources: [{ id: 'saved' }], models: [{ id: 'shared-model' }] }
  const state = renderHook(() => useOnboardingState())
  await waitFor(() => expect(state.result.current.loading).toBe(false))
  expect(state.result.current.hasModels).toBe(true)
  expect(state.result.current.visible).toBe(false)
  expect(nextOnboardingStep(state.result.current.value!, {})).toBe('agents')
})
