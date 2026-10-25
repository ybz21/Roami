// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import NativeConversation from './NativeConversation'
import { pairToolResults } from '../chat/useTranscript'
import { nativeTranscript } from './native-transcript'
import type { AgentMessage } from './agent-protocol'

vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
afterEach(cleanup)
const msg = (id: string, role: string, content: AgentMessage['content']): AgentMessage => ({ id, role, content, branch_id: 'child', seq: 1, status: 'completed' })
const use = (id: string, command: string) => ({ id, function: { name: 'bash', arguments: JSON.stringify({ command }) } })
const result = (id: string, text: string, state = 'succeeded') => msg('result-' + id, 'tool', { tool_call_id: id, text, toolState: state })
const show = (messages: AgentMessage[], active = false) => render(<I18nProvider><NativeConversation messages={messages} active={active} node={null} canAnswer={false} answer={async () => false} /></I18nProvider>)

it('uses the professional renderer to interleave commentary, commands, results and the final answer', () => {
  const page = show([
    msg('first', 'assistant', { text: 'Checking the build.', tool_calls: [use('build', 'node build.mjs')] }),
    result('build', 'Build passed'),
    msg('middle', 'assistant', { text: 'The build passed. Now checking the files.' }),
    msg('second', 'assistant', { tool_calls: [use('check', 'node check.mjs')] }),
    result('check', 'Checks passed'),
    msg('final', 'assistant', { text: 'Ready to review.' }),
  ])
  const order = [...page.container.querySelectorAll('.cc-msg')].map(item => item.getAttribute('data-msg-id'))
  expect(order).toEqual(['first', 'middle', 'second', 'final'])
  expect(screen.getByText('Checking the build.')).toBeTruthy()
  expect(screen.getByText('The build passed. Now checking the files.')).toBeTruthy()
  expect(page.container.querySelectorAll('.cc-cmd')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: /node build.mjs/ }))
  expect(screen.getByText('Build passed')).toBeTruthy()
})

it('shares successful run folding and keeps failures expanded', () => {
  const page = show([
    msg('one', 'assistant', { tool_calls: [use('one', 'node one.mjs')] }), result('one', 'one passed'),
    msg('two', 'assistant', { tool_calls: [use('two', 'node two.mjs')] }), result('two', 'two failed', 'failed'),
  ])
  expect(page.container.querySelector('.cc-run')).toBeTruthy()
  expect(page.container.querySelector('.cc-cmd.is-err')).toBeTruthy()
  expect(screen.getByText('two failed')).toBeTruthy()
  expect(screen.queryByText('one passed')).toBeNull()
  fireEvent.click(page.container.querySelector('.cc-run-head')!)
  expect(page.container.querySelectorAll('.cc-cmd')).toHaveLength(2)
})

it('keeps pending calls live and avoids showing an ended unknown result as successful', () => {
  const messages = [msg('pending', 'assistant', { tool_calls: [use('pending', 'node pending.mjs')] })]
  const page = show(messages, true)
  expect(page.container.querySelector('.cc-spin')).toBeTruthy()
  page.unmount()
  const ended = show(messages)
  expect(ended.container.querySelector('.cc-cmd.is-err')).toBeTruthy()
})

it('retains tool identities and errors across a pagination boundary', () => {
  const messages = [result('call', 'failed', 'failed'), msg('call', 'assistant', { tool_calls: [use('call', 'node test.mjs')] })]
  const blocks = nativeTranscript(messages)
  expect(blocks[0].blocks[0]).toMatchObject({ kind: 'tool_result', toolUseId: 'call', isError: true })
  expect(blocks[1].blocks[0]).toMatchObject({ kind: 'tool_use', name: 'Bash', id: 'call' })
})


it('shows native command streams without their JSON transport envelope', () => {
  const messages = [result('shell', JSON.stringify({ stdout: 'Build passed', stderr: 'One warning', exitCode: 0 }))]
  expect(nativeTranscript(messages)[0].blocks[0].text).toBe('Build passed\nOne warning')
})


it('keeps an attachment-only assistant message in its original conversation position', () => {
  show([
    msg('before', 'assistant', { text: 'Here is the draft.' }),
    msg('attachment', 'assistant', { attachments: [{ id: 'report', name: 'draft.pdf', mimeType: 'application/pdf', sizeBytes: 1024 }] }),
    msg('after', 'assistant', { text: 'Please review the document.' }),
  ])
  const file = screen.getByRole('link', { name: /draft.pdf/ })
  expect(screen.getByText('Here is the draft.').compareDocumentPosition(file) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(file.compareDocumentPosition(screen.getByText('Please review the document.')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it('pairs repeated provider call IDs within their own turn', () => {
  const first = { ...msg('first', 'assistant', { tool_calls: [use('call-0', 'first command')] }), turn_id: 'turn-one' }
  const second = { ...msg('second', 'assistant', { tool_calls: [use('call-0', 'second command')] }), turn_id: 'turn-two' }
  const messages = [first, { ...result('call-0', 'first output'), id: 'first-result', turn_id: first.turn_id }, second, { ...result('call-0', 'second error', 'failed'), id: 'second-result', turn_id: second.turn_id }]
  const { view, results } = pairToolResults(nativeTranscript(messages))
  const a = view[0].blocks[0].id!, b = view[1].blocks[0].id!
  expect(a).not.toBe(b)
  expect(results[a]).toMatchObject({ text: 'first output', isError: false })
  expect(results[b]).toMatchObject({ text: 'second error', isError: true })
})
