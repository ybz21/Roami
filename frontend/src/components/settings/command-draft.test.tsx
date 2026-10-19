// @vitest-environment jsdom
import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { TextControl } from './SettingRow'
afterEach(cleanup)
it('SET-02 preserves empty and trailing-space command drafts until blur', () => {
  const save = vi.fn()
  render(<TextControl label="Codex" get={() => 'codex'} set={save} />)
  const input = screen.getByRole('textbox', { name: 'Codex' })
  fireEvent.change(input, { target: { value: '' } })
  expect((input as HTMLInputElement).value).toBe('')
  fireEvent.change(input, { target: { value: '/opt/my ' } })
  expect((input as HTMLInputElement).value).toBe('/opt/my ')
  expect(save).not.toHaveBeenCalled()
  fireEvent.change(input, { target: { value: '/opt/my codex' } })
  fireEvent.blur(input)
  expect(save).toHaveBeenCalledTimes(1)
  expect(save).toHaveBeenCalledWith('/opt/my codex')
})
