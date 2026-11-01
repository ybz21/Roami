// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { I18nProvider } from '../../i18n'
import OnboardingRoami from './OnboardingRoami'

const fixture = vi.hoisted(() => ({ api: vi.fn(), catalog: {} as any, models: { verified: true }, fail: false }))
vi.mock('../../api', () => ({ api: (...args: any[]) => fixture.api(...args) }))
vi.mock('./onboarding-state', () => ({ onboardingChanged: vi.fn(), useOnboardingState: () => ({ value: { models: fixture.models }, loading: false }) }))
beforeEach(() => {
  localStorage.clear(); localStorage.setItem('ttmux-locale', 'zh-CN')
  fixture.fail = false; fixture.models.verified = true
  fixture.catalog = { revision: 'r1', sources: [], models: [
    { id: 'original', name: 'Original model', protocol: 'openai-completions' },
    { id: 'next', name: 'Next model', protocol: 'openai-completions' },
    { id: 'codex', name: 'Responses only', protocol: 'openai-responses' },
  ], roamiModels: { main: 'original', worker: 'original' } }
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  fixture.api.mockReset().mockImplementation(async (_method, path, body) => {
    if (path === '/agent/model-gateway/catalog') return { data: structuredClone(fixture.catalog) }
    if (path === '/agent/model-gateway/catalog/roles') { fixture.catalog = { ...fixture.catalog, revision: 'r2', roamiModels: { main: body.main, worker: body.worker } }; fixture.models.verified = false; return { data: fixture.catalog } }
    if (path === '/agent/model-settings/verify') { if (fixture.fail) throw new Error('offline'); fixture.models.verified = true; return { data: fixture.models } }
    return { data: {} }
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const show = (ready = vi.fn(), nav = vi.fn()) => ({ ready, nav, ...render(<I18nProvider><App><OnboardingRoami onNav={nav} onReadyChange={ready} /></App></I18nProvider>) })
it('reuses catalog role binding and requires verification after changing the selected model', async () => {
  const view = show()
  await waitFor(() => expect(view.ready).toHaveBeenLastCalledWith(true))
  expect(screen.getByText('模型能力与上下文', { selector: 'summary' })).toBeTruthy()
  fireEvent.mouseDown(screen.getAllByRole('combobox')[0])
  fireEvent.click(await screen.findByText('Next model', { selector: '.ant-select-item-option-content' }))
  await waitFor(() => expect(view.ready).toHaveBeenLastCalledWith(false))
  expect(screen.getByText('Responses only', { selector: '.ant-select-item-option-content' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /应\s*用/ }))
  fireEvent.click((await screen.findByRole('dialog')).querySelector('.ant-btn-primary')!)
  await waitFor(() => expect(fixture.api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/roles', { main: 'next', worker: 'original', revision: 'r1', restore: false }))
  expect(view.ready).toHaveBeenLastCalledWith(false)
  await waitFor(() => expect((screen.getByRole('button', { name: '验证可用性' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '验证可用性' }))
  await waitFor(() => expect(view.ready).toHaveBeenLastCalledWith(true))
})
it('does not mark a failed verification ready even with previously saved evidence', async () => {
  const view = show()
  await waitFor(() => expect(view.ready).toHaveBeenLastCalledWith(true))
  fixture.fail = true
  fireEvent.click(screen.getByRole('button', { name: '验证可用性' }))
  await screen.findByText('配置已保存，但调用验证未通过。请检查连接后重试。')
  expect(view.ready).toHaveBeenLastCalledWith(false)
})
it('preserves an unapplied model choice when revisiting the setup step', async () => {
  const first = show()
  await waitFor(() => expect(first.ready).toHaveBeenLastCalledWith(true))
  fireEvent.mouseDown(screen.getAllByRole('combobox')[0])
  fireEvent.click(await screen.findByText('Next model', { selector: '.ant-select-item-option-content' }))
  first.unmount()
  const second = show()
  await screen.findByText('已恢复未保存的草稿。关闭或刷新前请保存。')
  expect(screen.getByText('Next model', { selector: '.ant-select-selection-item' })).toBeTruthy()
  await waitFor(() => expect(second.ready).toHaveBeenLastCalledWith(false))
  fireEvent.mouseDown(screen.getAllByRole('combobox')[0])
  fireEvent.click(await screen.findByText('Original model', { selector: '.ant-select-item-option-content' }))
  await waitFor(() => expect(second.ready).toHaveBeenLastCalledWith(true))
})
it('keeps an empty catalog incomplete and points to unified model source management', async () => {
  fixture.catalog.models = []; fixture.catalog.roamiModels = {}
  const view = show()
  await screen.findByText('先添加模型连接，再为智能体选择模型。')
  expect(view.ready).toHaveBeenLastCalledWith(false)
  expect((screen.getByRole('button', { name: '验证可用性' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '管理模型' }))
  expect(view.nav).toHaveBeenCalledWith('onboarding/model')
})
