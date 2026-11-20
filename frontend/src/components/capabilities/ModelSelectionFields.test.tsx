// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { api } from '../../api'
import ModelSelectionFields, { type ModelChoice } from './ModelSelectionFields'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', () => ({
  Alert: ({ message }: { message: string }) => <p role="alert">{message}</p>, Spin: () => null,
  Checkbox: ({ children, checked, onChange }: any) => <label><input type="checkbox" checked={checked} onChange={onChange} />{children}</label>,
  Select: ({ options, onChange, ...props }: any) => <select aria-label={props['aria-label']} value={props.value} onChange={event => onChange(event.target.value)}>{options.map((option: any) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>,
}))
afterEach(() => { cleanup(); vi.clearAllMocks() })
beforeEach(() => {
 vi.mocked(api).mockResolvedValue({ data: { models: [
  { id: 'vision', name: 'Vision', kind: 'single', configured: true, enabled: true, freeOnly: false, protocol: 'openai-completions', capabilities: { image: { support: 'supported' } } },
  { id: 'free-pool', name: 'Saved free pool', kind: 'aggregate', configured: true, enabled: true, freeOnly: true, protocol: 'openai-completions', capabilities: {} },
  { id: 'free-vision', name: 'Free vision', kind: 'single', configured: true, enabled: true, pricing: 'confirmed-free', protocol: 'openai-completions', capabilities: {} },
  { id: 'disabled', name: 'Disabled', configured: true, enabled: false, protocol: 'openai-completions', capabilities: {} },
  { id: 'upstream', name: 'Upstream', configured: false, enabled: true, protocol: 'openai-completions', capabilities: {} },
  { id: 'responses', name: 'Responses only', configured: true, enabled: true, protocol: 'unsupported-protocol', capabilities: {} },
 ] } })
})
it('offers only configured enabled compatible models and preserves a chosen route when filtering', async () => {
 function Form() { const [value, setValue] = useState<ModelChoice>({ model: 'auto', freeOnly: false }); return <><ModelSelectionFields value={value} onChange={setValue} /><output>{JSON.stringify(value)}</output></> }
 render(<Form />)
 await screen.findByRole('option', { name: 'Vision' })
 const options = screen.getByLabelText('agent.composer.model').querySelectorAll('option')
 expect([...options].map(option => option.value)).toEqual(['auto', 'free-pool', 'vision', 'free-vision'])
 expect(screen.queryByRole('option', { name: 'Disabled' })).toBeNull()
 expect(screen.queryByRole('option', { name: 'Upstream' })).toBeNull()
 expect(screen.queryByRole('option', { name: 'Responses only' })).toBeNull()
 fireEvent.change(screen.getByLabelText('agent.composer.model'), { target: { value: 'vision' } })
 fireEvent.click(screen.getByLabelText('modelSelection.freeOnly'))
 expect(screen.getByRole('option', { name: 'Vision' })).toBeTruthy()
 expect(screen.getByRole('option', { name: 'Free vision' })).toBeTruthy()
 expect(screen.getByRole('alert').textContent).toBe('modelSelection.freeUnconfirmed')
 expect(screen.getByRole('status').textContent).toContain('"freeOnly":true')
 await waitFor(() => expect(api).toHaveBeenCalledTimes(1))
 expect(vi.mocked(api).mock.calls[0][0]).toBe('GET')
})
