import workerSource from '../public/sw.js?raw'
import { expect, it, vi } from 'vitest'

function worker() {
  const listeners = new Map<string, (event: any) => void>()
  const showNotification = vi.fn(async (_title: string, _options: any) => {})
  const openWindow = vi.fn(async (_path: string) => {})
  const setAppBadge = vi.fn(async (_count: number) => {})
  const fetch = vi.fn()
  const self = {
    addEventListener: (name: string, handler: (event: any) => void) => listeners.set(name, handler),
    navigator: { language: 'en-US', setAppBadge, clearAppBadge: vi.fn() },
    registration: { showNotification },
    clients: { matchAll: async () => [], openWindow },
  }
  new Function('self', 'fetch', workerSource)(self, fetch)
  async function dispatch(name: string, fields: any) {
    let pending: Promise<unknown> | undefined
    listeners.get(name)!({ ...fields, waitUntil: (value: Promise<unknown>) => { pending = value } })
    await pending
  }
  return { dispatch, showNotification, openWindow, setAppBadge, fetch }
}

it('shows a hidden preview with the canonical agent badge and routes to the original message', async () => {
  const w = worker()
  await w.dispatch('push', { data: { json: () => ({ id: 42, type: 'agent.message', conversation: 'conversation', branch: 'branch', message: 'message', title: 'Roami', body: '', hidePreview: true, locale: 'en-US', badge: 7 }) } })
  const [title, options] = w.showNotification.mock.calls[0]
  expect(title).toBe('Roami')
  expect(options.body).toBe('New message from your agent')
  expect(options.tag).toBe('agent:conversation')
  expect(w.setAppBadge).toHaveBeenCalledWith(7)
  await w.dispatch('notificationclick', { notification: { data: options.data, close: vi.fn() } })
  expect(w.openWindow).toHaveBeenCalledWith('/#/home/conversation/branch/message')
})

it('does not treat agent notifications as terminal approval actions or allow arbitrary navigation', async () => {
  const w = worker()
  await w.dispatch('notificationclick', { action: 'allow', notification: { data: { type: 'agent.message', session: 'not-a-terminal', conversation: 'https://evil.test', branch: 'branch', message: 'message' }, close: vi.fn() } })
  expect(w.fetch).not.toHaveBeenCalled()
  expect(w.openWindow).toHaveBeenCalledWith('/#/home')
})
