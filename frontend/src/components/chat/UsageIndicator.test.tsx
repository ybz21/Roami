// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { UsageIndicator } from './UsageIndicator'

vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string) => key }) }))
afterEach(cleanup)

it('omits missing metrics and displays zero values without disabled controls', () => {
  const page = render(<UsageIndicator />)
  expect(page.container.childElementCount).toBe(0)
  page.rerender(<UsageIndicator quota={0} elapsed={0} />)
  expect(screen.getByText('0%')).toBeTruthy()
  expect(screen.getByText('0s')).toBeTruthy()
  expect(screen.queryByRole('button')).toBeNull()
})

it('keeps quota warning levels and allows a custom normal accent', () => {
  const page = render(<UsageIndicator quota={4} accent="var(--ok)" />)
  expect(screen.getByText('4%').style.color).toBe('var(--ok)')
  page.rerender(<UsageIndicator quota={85} />)
  expect(screen.getByText('85%').style.color).toBe('var(--warn)')
  page.rerender(<UsageIndicator quota={95} />)
  expect(screen.getByText('95%').style.color).toBe('var(--danger)')
})

it('opens elapsed details only through its own action', () => {
  const open = vi.fn()
  const page = render(<UsageIndicator quota={4} elapsed={20_520_000} onElapsedClick={open} elapsedExpanded={false} />)
  fireEvent.click(screen.getByText('4%'))
  expect(open).not.toHaveBeenCalled()
  const button = screen.getByRole('button', { name: 'chat.elapsedTitle' })
  expect(button.textContent).toBe('5h 42m')
  expect(button.getAttribute('aria-expanded')).toBe('false')
  fireEvent.click(button)
  expect(open).toHaveBeenCalledTimes(1)
  page.rerender(<UsageIndicator elapsed={20_520_000} onElapsedClick={open} elapsedExpanded />)
  expect(screen.getByRole('button').getAttribute('aria-expanded')).toBe('true')
  expect(screen.queryByText('chat.quotaTitle')).toBeNull()
})
