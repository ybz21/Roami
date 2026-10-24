// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { buildSettings } from './registry'
vi.mock('../agent/AgentImprovement', () => ({ default: () => null }))

const deps = { t: (key: string) => key, theme: 'dark', setTheme: vi.fn(), locale: 'zh-CN', setLocale: vi.fn(), prefs: {}, setPrefs: vi.fn(), setWorkspace: vi.fn(), nodeLabel: '', isHub: false, onBrowserRestart: vi.fn(), onEnvPush: vi.fn() }
it.each([undefined, false, true])('registers the experimental workflow only for an explicitly confirmed development node (%s)', developmentRsi => {
  const model = buildSettings({ ...deps, developmentRsi, nodeId: 'dev-node' })
  expect(!!model.pages['experiments.rsi']).toBe(developmentRsi === true)
  expect(model.nodes.some(node => node.kind === 'leaf' && node.page === 'experiments.rsi')).toBe(developmentRsi === true)
  expect(model.order.includes('experiments.rsi')).toBe(developmentRsi === true)
  expect(model.nodes.some(node => node.kind === 'section' && node.title === 'agent.experiment.title')).toBe(developmentRsi === true)
  if (developmentRsi) {
    const control = model.pages['experiments.rsi'].items[0].control
    expect(control.kind).toBe('custom')
    if (control.kind === 'custom') expect((control.node as any).props).toMatchObject({ node: 'dev-node', workflow: true })
  }
})
