// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentQuestion from './AgentQuestion'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)
const question = { prompt: 'Which Codex?', options: [{ label: 'A', description: 'Recommended' }, { label: 'B' }] }
it('answers through selectable choices once, without a text field', async () => {
  const answer = vi.fn().mockResolvedValue(true)
  render(<AgentQuestion question={question} disabled={false} answer={answer} />)
  expect(screen.queryByRole('textbox')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'A Recommended' }))
  fireEvent.click(screen.getByRole('button', { name: 'B' }))
  await waitFor(() => expect(answer).toHaveBeenCalledTimes(1))
  expect(answer).toHaveBeenCalledWith('A')
  expect((screen.getByRole('button', { name: 'B' }) as HTMLButtonElement).disabled).toBe(true)
})
it('allows retry after a failed message submission and disables historical choices', async () => {
  const answer = vi.fn().mockResolvedValue(false)
  const view = render(<AgentQuestion question={question} disabled={false} answer={answer} />)
  fireEvent.click(screen.getByRole('button', { name: 'B' }))
  await waitFor(() => expect((screen.getByRole('button', { name: 'B' }) as HTMLButtonElement).disabled).toBe(false))
  view.rerender(<AgentQuestion question={question} disabled answer={answer} />)
  fireEvent.click(screen.getByRole('button', { name: 'A Recommended' }))
  expect(answer).toHaveBeenCalledTimes(1)
})
