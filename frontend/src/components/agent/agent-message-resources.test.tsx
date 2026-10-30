// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { setCurrentNode } from '../cluster/node-url'
import AgentMessageView from './AgentMessageView'
import type { AgentMessage } from './agent-protocol'

vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('antd', () => ({ App: { useApp: () => ({ message: { error: vi.fn() } }) } }))
vi.mock('../markdown/Markdown', () => import('../markdown/MarkdownImpl'))
afterEach(() => { cleanup(); setCurrentNode(null) })

const item: AgentMessage = { id: 'message', role: 'assistant', status: 'completed', seq: 1, branch_id: 'branch', content: { text: '[report](/api/agent/artifacts/report/content)\n\n[file](/api/file/raw?path=%2Ftmp%2Fa%20b.txt)\n\n[PR](https://github.com/ybz21/Roami/pull/353)\n\n![chart](/api/agent/artifacts/chart/content)', attachments: [{ id: 'attachment', name: 'result.txt', mimeType: 'text/plain', sizeBytes: 12 }] } }

it('keeps rendered links, images and attachments on the message origin after the current node changes', () => {
  setCurrentNode('different-node')
  const { rerender } = render(<AgentMessageView item={item} node="origin" focused={false} remember={vi.fn()} />)
  expect(screen.getByRole('link', { name: 'report' }).getAttribute('href')).toBe('/n/origin/api/agent/artifacts/report/content')
  expect(screen.getByRole('link', { name: 'file' }).getAttribute('href')).toBe('/n/origin/api/file/raw?path=%2Ftmp%2Fa%20b.txt')
  expect(screen.getByRole('img', { name: 'chart' }).getAttribute('src')).toBe('/n/origin/api/agent/artifacts/chart/content')
  expect(screen.getByRole('link', { name: /result.txt/ }).getAttribute('href')).toBe('/n/origin/api/agent/artifacts/attachment/content')
  expect(screen.getByRole('link', { name: 'PR' }).getAttribute('href')).toBe('https://github.com/ybz21/Roami/pull/353')
  rerender(<AgentMessageView item={item} node={null} focused={false} remember={vi.fn()} />)
  expect(screen.getByRole('link', { name: 'report' }).getAttribute('href')).toBe('/api/agent/artifacts/report/content')
})

it('opens legacy local file links from reported results through the origin file service', () => {
  const path = '/home/ai/.roami/workspaces/agent-coding/'
  const report = { ...item, content: { text: `[index.html](${path}index.html)\n\n[shot-desktop.png](${path}shot-desktop.png)\n\n![mobile](${path}shot-mobile-full.png)` } }
  setCurrentNode('different-node')
  render(<AgentMessageView item={report} node="origin" focused={false} remember={vi.fn()} />)
  expect(screen.getByRole('link', { name: 'index.html' }).getAttribute('href')).toBe('/n/origin/api/file' + path + 'index.html')
  expect(screen.getByRole('link', { name: 'shot-desktop.png' }).getAttribute('href')).toBe('/n/origin/api/file' + path + 'shot-desktop.png')
  expect(screen.getByRole('img', { name: 'mobile' }).getAttribute('src')).toBe('/n/origin/api/file' + path + 'shot-mobile-full.png')
})
