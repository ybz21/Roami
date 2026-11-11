// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { buildSettings } from './registry'
vi.mock('../agent/AgentImprovement', () => ({ default: () => null }))

const deps = { t: (key: string) => key, theme: 'dark', setTheme: vi.fn(), locale: 'zh-CN', setLocale: vi.fn(), prefs: {}, setPrefs: vi.fn(), setWorkspace: vi.fn(), nodeLabel: '', isHub: false, onBrowserRestart: vi.fn(), onEnvPush: vi.fn() }
it.each([undefined, false, true])('registers the experimental workflow only for an explicitly confirmed development node (%s)', developmentRsi => {
  const model = buildSettings({ ...deps, developmentRsi, nodeId: 'dev-node' })
  expect(!!model.pages['experiments.rsi']).toBe(developmentRsi === true)
  expect(model.groups.find(group => group.title === 'set.groupAgent')?.pages.includes('experiments.rsi') ?? false).toBe(developmentRsi === true)
  expect(model.order.includes('experiments.rsi')).toBe(developmentRsi === true)
  if (developmentRsi) {
    const control = model.pages['experiments.rsi'].items[0].control
    expect(control.kind).toBe('custom')
    if (control.kind === 'custom') expect((control.node as any).props).toMatchObject({ node: 'dev-node', workflow: true })
  }
})

it('keeps device and account settings while removing migrated agent pages from navigation and search', () => {
  const model = buildSettings(deps)
  expect(model.groups).toEqual([
    { title: 'set.groupPreferences', pages: ['ui.look', 'ui.layout', 'ui.keys', 'agent.new'] },
    { title: 'set.groupNotifications', pages: ['agent.messages'] },
    { title: 'set.groupDevices', pages: ['node.browser', 'node.phone', 'node.p2p', 'cluster'] },
    { title: 'set.groupSystem', pages: ['node.env', 'sec', 'about'] },
  ])
  expect(new Set(model.order).size).toBe(12)
  expect(model.pages['agent.runtime']).toBeUndefined()
  expect(model.pages['agent.memory']).toBeUndefined()
  for (const id of model.order) expect(model.pages[id].parent).toBe(model.groups.find(group => group.pages.includes(id))!.title)
  expect(model.pages['node.memory']).toBeTruthy()
  expect(model.order).not.toContain('node.memory')
  expect(model.pages['node.speech']).toBeUndefined()
})

it('moves fullscreen and sign-out without dropping their controllers or their search terms', () => {
  const fullscreen = { active: true, toggle: vi.fn() }, onLogout = vi.fn()
  const model = buildSettings({ ...deps, fullscreen, onLogout })
  expect(model.pages['ui.look'].items.map(item => item.id)).not.toContain('account')
  const display = model.pages['ui.layout'].items.find(item => item.id === 'fullscreen')!
  expect(display.scope).toBe('browser')
  if (display.control.kind === 'custom') expect((display.control.node as any).props.controller).toBe(fullscreen)
  const account = model.pages.sec.items.find(item => item.id === 'logout')!
  expect(account.scope).toBe('browser')
  if (account.control.kind === 'custom') expect((account.control.node as any).props.onLogout).toBe(onLogout)
  expect(model.pages['agent.messages'].items.find(item => item.id === 'push')!.scope).toBe('browser')
  expect(model.pages['agent.new'].items.find(item => item.id === 'showVoiceButton')!.scope).toBe('mine')
})
