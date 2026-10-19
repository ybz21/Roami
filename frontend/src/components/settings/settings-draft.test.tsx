// @vitest-environment jsdom
import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useSettingsDraft } from './settings-draft'
let node = 'draft-node'
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => node }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)
function Form({ id }: { id: string }) {
  const [value, setValue] = useState(''), [baseline, setBaseline] = useState('')
  const notice = useSettingsDraft(id, value, baseline, setValue)
  return <>{notice}<input aria-label="key" value={value} onChange={e => setValue(e.target.value)} /><button onClick={() => setBaseline(value)}>save</button></>
}
it('SET-05 recovers edits after unmount, warns on reload, and keeps secrets out of storage', async () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem')
  const first = render(<Form id="recover" />)
  fireEvent.change(screen.getByLabelText('key'), { target: { value: 'private-draft' } })
  const unload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(unload)
  expect(unload.defaultPrevented).toBe(true)
  first.unmount()
  render(<Form id="recover" />)
  await waitFor(() => expect((screen.getByLabelText('key') as HTMLInputElement).value).toBe('private-draft'))
  expect(screen.getByRole('status').textContent).toBe('settings.draftRestored')
  expect(storage).not.toHaveBeenCalled()
  storage.mockRestore()
})
it('SET-05 isolates nodes and clears the draft after saving', async () => {
  node = 'original'
  const first = render(<Form id="isolation" />)
  fireEvent.change(screen.getByLabelText('key'), { target: { value: 'node-only' } })
  first.unmount(); node = 'other'
  const second = render(<Form id="isolation" />)
  expect((screen.getByLabelText('key') as HTMLInputElement).value).toBe('')
  second.unmount(); node = 'original'
  const third = render(<Form id="isolation" />)
  await waitFor(() => expect((screen.getByLabelText('key') as HTMLInputElement).value).toBe('node-only'))
  fireEvent.click(screen.getByText('save'))
  third.unmount()
  render(<Form id="isolation" />)
  expect((screen.getByLabelText('key') as HTMLInputElement).value).toBe('')
})
