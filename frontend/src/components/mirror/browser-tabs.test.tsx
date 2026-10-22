// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { TabSheet } from './browser-tabs'

afterEach(cleanup)

describe('mobile browser tab actions', () => {
  it('pinning from a tab menu leaves the sheet open and does not select the tab', async () => {
    const onSelect = vi.fn()
    const onPin = vi.fn()
    const onClose = vi.fn()
    render(<I18nProvider><TabSheet open tabs={[{ id: 'a', title: 'A', url: 'https://example.com' }]}
      active="a" pinned={new Set()} onClose={onClose} onSelect={onSelect} onCloseTab={vi.fn()}
      onCloseMany={vi.fn()} onPin={onPin} onAdd={vi.fn()} /></I18nProvider>)
    fireEvent.click(screen.getByRole('button', { name: '更多' }))
    fireEvent.click(await screen.findByText('固定标签'))
    expect(onPin).toHaveBeenCalledWith('a')
    expect(onSelect).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeTruthy()
  })
})

it('separates human and Agent pages and exposes source changes and sleeping state', async () => {
  const onOrigin = vi.fn(), onSelect = vi.fn()
  render(<I18nProvider><TabSheet open tabs={[
    { id: 'human', title: 'My page', url: 'https://human.test', origin: 'human' },
    { id: 'agent', title: 'Research', url: 'https://agent.test', origin: 'agent', sleeping: true },
  ]} active="human" pinned={new Set()} onClose={vi.fn()} onSelect={onSelect} onCloseTab={vi.fn()}
    onCloseMany={vi.fn()} onPin={vi.fn()} onOrigin={onOrigin} onAdd={vi.fn()} /></I18nProvider>)
  expect(screen.queryByText('Research')).toBeNull()
  fireEvent.click(screen.getByText('智能体 (1)'))
  expect(onSelect).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog')).toBeTruthy()
  expect(screen.getByText('休眠')).toBeTruthy()
  expect(screen.queryByText('My page')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '更多' }))
  fireEvent.click(await screen.findByText('移到人工组'))
  expect(onOrigin).toHaveBeenCalledWith('agent', 'human')
})
