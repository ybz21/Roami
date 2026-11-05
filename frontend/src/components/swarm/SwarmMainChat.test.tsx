// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { TextareaHTMLAttributes } from 'react'
import SwarmMainChat from './SwarmMainChat'

const state = vi.hoisted(() => ({ api: vi.fn(), refresh: vi.fn(), node: null as string | null, phone: false }))
vi.mock('../../api', () => ({ api: state.api }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: state.phone }) }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => state.node, nodeApi: (path: string) => (state.node || 'local') + path }))
vi.mock('../agent/useAgentThread', () => ({ useAgentThread: () => ({ view: null, refresh: state.refresh }) }))
vi.mock('../agent/NativeConversation', () => ({ default: ({ answer }: { answer: (value: string) => Promise<boolean> }) => <button onClick={() => void answer('An answer')}>Answer</button> }))
vi.mock('antd', () => ({
  Input: { TextArea: ({ autoSize: _autoSize, variant: _variant, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { autoSize?: unknown; variant?: unknown }) => <textarea {...props} /> },
  Spin: () => <span>Pending</span>,
}))
beforeEach(() => { localStorage.clear(); state.node = null; state.phone = false; state.api.mockReset(); state.refresh.mockReset(); state.api.mockResolvedValue({ data: { kind: 'project_main', projectId: 'project', conversationId: 'project-main' } }) })
afterEach(cleanup)
const renderChat = () => render(<SwarmMainChat conversationId="project-main" projectId="project" onSent={async () => {}} />)
const write = (text: string) => fireEvent.change(screen.getByRole('textbox'), { target: { value: text } })

it('uses the global composer and sends only to the independent project Main', async () => {
  const view = renderChat()
  expect(view.container.querySelector('.conversation-composer')).toBeTruthy()
  write('Please coordinate the team')
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(state.refresh).toHaveBeenCalled())
  expect(state.api.mock.calls.map(call => call.slice(0, 2))).toEqual([
    ['GET', '/agent/conversations/project-main/identity'], ['POST', '/agent/conversations/project-main/messages'],
  ])
  expect(state.api.mock.calls[1][2].text).toBe('Please coordinate the team')
})

it('preserves a failed request key and its draft across closing and reopening', async () => {
  state.api.mockImplementation(async (method: string) => {
    if (method === 'POST') throw new Error('Unknown delivery')
    return { data: { kind: 'project_main', projectId: 'project', conversationId: 'project-main' } }
  })
  const view = renderChat(); write('Keep this request')
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await screen.findByRole('alert')
  const first = state.api.mock.calls.find(call => call[0] === 'POST')![2]
  view.unmount(); renderChat()
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep this request')
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[0] === 'POST')).toHaveLength(2))
  expect(state.api.mock.calls.filter(call => call[0] === 'POST')[1][2]).toEqual(first)
})

it.each(['home_main', 'another_project'])('rejects an identity from %s without publishing to group chat', async kind => {
  state.api.mockResolvedValue({ data: { kind, projectId: 'another', conversationId: 'project-main' } })
  renderChat(); write('For this project only')
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await screen.findByRole('alert')
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})

it('does not submit after the node changes during an identity read', async () => {
  let resolve!: (value: unknown) => void
  state.api.mockImplementation(() => new Promise(done => { resolve = done }))
  const view = renderChat(); write('Stay here')
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  state.node = 'another'; view.rerender(<SwarmMainChat conversationId="project-main" projectId="project" onSent={async () => {}} />)
  resolve({ data: { kind: 'project_main', projectId: 'project', conversationId: 'project-main' } })
  await waitFor(() => expect(state.api).toHaveBeenCalledTimes(1))
  expect(state.api.mock.calls[0][0]).toBe('GET')
})

it('preserves typing made while a send is pending and answers without consuming the draft', async () => {
  let resolve!: (value: unknown) => void
  state.api.mockImplementation(async (method: string) => method === 'GET' ? { data: { kind: 'project_main', projectId: 'project', conversationId: 'project-main' } } : new Promise(done => { resolve = done }))
  renderChat(); write('First request')
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(state.api).toHaveBeenCalledTimes(2))
  write('Next draft'); resolve({ data: {} })
  await waitFor(() => expect(state.refresh).toHaveBeenCalledTimes(1))
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Next draft')
  fireEvent.click(screen.getByRole('button', { name: 'Answer' }))
  await waitFor(() => expect(state.api).toHaveBeenCalledTimes(4))
  resolve({ data: {} })
  await waitFor(() => expect(state.refresh).toHaveBeenCalledTimes(2))
  expect(state.api.mock.calls[3][2].text).toBe('An answer')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Next draft')
})

it('keeps phone Enter as a newline', () => {
  state.phone = true; renderChat(); write('A phone draft')
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
  expect(state.api).not.toHaveBeenCalled()
})
