// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { useViewState } from '../view-state'
import AppRoutes from './AppRoutes'

const lifecycle = vi.hoisted(() => ({ mount: vi.fn() }))
vi.mock('../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../components/mirror/BrowserView', () => ({ default: () => { useEffect(() => { lifecycle.mount() }, []); const [value, setValue] = useViewState('address', ''); return <input aria-label="address" value={value} onChange={event => setValue(event.target.value)} /> } }))
vi.mock('../components/settings/SettingsPage', () => ({ default: ({ sub }: any) => { const [value, setValue] = useState(''); return <input aria-label={sub || 'settings'} value={value} onChange={event => setValue(event.target.value)} /> } }))
vi.mock('../components/projects/Projects', () => ({ default: () => null }))
afterEach(cleanup)

it('retains each page across navigation and session focus, releases closed pages, and isolates nodes', async () => {
  const props: any = {
    routing: { route: 'browser', tab: 'browser', go: vi.fn() }, isMobile: false, active: null, projects: [], actions: {},
    mobileProject: null, mobileSearchNonce: 0, mobileActionsHost: null, agent: { node: 'one' }, openPages: ['browser', 'settings'],
  }
  const rendered = render(<AppRoutes {...props} />)
  fireEvent.change(await screen.findByRole('textbox', { name: 'address' }), { target: { value: 'unfinished address' } })
  const settings = { route: 'settings/browser', tab: 'settings', settingsSub: 'browser', go: vi.fn() }
  rendered.rerender(<AppRoutes {...props} routing={settings} />)
  fireEvent.change(await screen.findByRole('textbox', { name: 'browser' }), { target: { value: 'unsaved setting' } })
  expect(screen.queryByRole('textbox', { name: 'address' })).toBeNull()
  rendered.rerender(<AppRoutes {...props} visible={false} routing={settings} />)
  expect(screen.queryByRole('textbox')).toBeNull()
  rendered.rerender(<AppRoutes {...props} />)
  expect((await screen.findByRole('textbox', { name: 'address' }) as HTMLInputElement).value).toBe('unfinished address')
  rendered.rerender(<AppRoutes {...props} routing={settings} />)
  expect((screen.getByRole('textbox', { name: 'browser' }) as HTMLInputElement).value).toBe('unsaved setting')
  rendered.rerender(<AppRoutes {...props} routing={settings} openPages={['settings']} />)
  rendered.rerender(<AppRoutes {...props} />)
  expect((await screen.findByRole('textbox', { name: 'address' }) as HTMLInputElement).value).toBe('')
  fireEvent.change(screen.getByRole('textbox', { name: 'address' }), { target: { value: 'node one' } })
  rendered.rerender(<AppRoutes {...props} agent={{ node: 'two' }} />)
  expect((await screen.findByRole('textbox', { name: 'address' }) as HTMLInputElement).value).toBe('')
})

it('separates browser task resources and restores each node without mixing choices', async () => {
  const props: any = { routing: { route: 'browser', tab: 'browser', go: vi.fn() }, isMobile: false, active: null, projects: [], actions: {}, mobileProject: null, mobileSearchNonce: 0, mobileActionsHost: null, agent: { node: 'one' }, openPages: ['browser'] }
  const rendered = render(<AppRoutes {...props} />)
  fireEvent.change(await screen.findByRole('textbox', { name: 'address' }), { target: { value: 'normal browser draft' } })
  rendered.rerender(<AppRoutes {...props} routing={{ ...props.routing, route: 'browser/task/instance/target' }} />)
  expect((await screen.findByRole('textbox', { name: 'address' }) as HTMLInputElement).value).toBe('')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'task browser draft' } })
  rendered.rerender(<AppRoutes {...props} />)
  expect((await screen.findByRole('textbox') as HTMLInputElement).value).toBe('normal browser draft')
  rendered.rerender(<AppRoutes {...props} agent={{ node: 'two' }} />)
  expect((await screen.findByRole('textbox') as HTMLInputElement).value).toBe('')
  rendered.rerender(<AppRoutes {...props} />)
  expect((await screen.findByRole('textbox') as HTMLInputElement).value).toBe('normal browser draft')
})

it('recreates controllers between the local node and a remote node named local', async () => {
  lifecycle.mount.mockClear()
  const props: any = { routing: { route: 'browser', tab: 'browser', go: vi.fn() }, isMobile: false, active: null, projects: [], actions: {}, mobileProject: null, mobileSearchNonce: 0, mobileActionsHost: null, agent: { node: null }, openPages: ['browser'] }
  const rendered = render(<AppRoutes {...props} />)
  fireEvent.change(await screen.findByRole('textbox'), { target: { value: 'local draft' } })
  rendered.rerender(<AppRoutes {...props} agent={{ node: 'local' }} />)
  expect((await screen.findByRole('textbox') as HTMLInputElement).value).toBe('')
  expect(lifecycle.mount).toHaveBeenCalledTimes(2)
  rendered.rerender(<AppRoutes {...props} />)
  expect((await screen.findByRole('textbox') as HTMLInputElement).value).toBe('local draft')
  expect(lifecycle.mount).toHaveBeenCalledTimes(3)
})
