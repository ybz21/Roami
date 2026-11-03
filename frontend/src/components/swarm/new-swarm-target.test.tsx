// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NewSwarmModal } from './NewSwarmModal'
const test = vi.hoisted(() => ({ api: vi.fn(), projects: [] as { key: string; dir: string }[] }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => test.api(...args) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../sessions/DirPicker', () => ({ DirPicker: () => null }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: vi.fn() } }) },
  Input: Object.assign(({ value, onChange, readOnly }: React.InputHTMLAttributes<HTMLInputElement>) => <input value={value} onChange={onChange} readOnly={readOnly} />, { TextArea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> }),
  Select: ({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: { value: string; label: string }[] }) => <select value={value} onChange={event => onChange(event.target.value)}>{options.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>,
  Modal: ({ children, onOk, okText, okButtonProps }: { children: ReactNode; onOk: () => void; okText: string; okButtonProps: { disabled: boolean } }) => <div>{children}<button disabled={okButtonProps.disabled} onClick={onOk}>{okText}</button></div>,
}))
beforeEach(() => {
  test.projects = []
  test.api.mockReset().mockImplementation(async (method: string, path: string) => ({ data: path === '/agent/conversations' ? [{ id: 'main', title: 'Main' }] : path === '/agent/main-conversation' ? { id: 'main' } : path === '/projects' ? { projects: test.projects } : { id: 'sw-created' } }))
})
afterEach(cleanup)
it.each([true, false])('uses registered project identity when matched: %s', async registered => {
  test.projects = registered ? [{ key: 'project-id', dir: '/registered' }] : []
  render(<NewSwarmModal open initialDir="/registered" lockDir onClose={vi.fn()} onDone={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('swarm.managed.name'), { target: { value: 'Team' } })
  fireEvent.change(screen.getByLabelText('swarm.managed.goal'), { target: { value: 'Create and verify deliverables' } })
  await waitFor(() => expect((screen.getByRole('button', { name: 'file.create' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: 'file.create' }))
  await waitFor(() => expect(test.api).toHaveBeenCalledWith('POST', '/agent/swarms', expect.objectContaining({ target: registered ? { kind: 'project', projectId: 'project-id' } : { kind: 'new_session', directory: '/registered' } })))
})
