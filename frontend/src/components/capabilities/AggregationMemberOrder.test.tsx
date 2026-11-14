// @vitest-environment jsdom
import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AggregationMemberOrder from './AggregationMemberOrder'
import type { CatalogModel } from './model-hub-api'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, values?: Record<string, unknown>) => key + (values?.model ? ' ' + values.model : ''), locale: 'en-US' }) }))
const initial: CatalogModel = { id: 'pool', name: 'Pool', aggregate: true, protocol: 'openai-completions', strategy: 'order', candidates: [{ sourceId: 'a', model: 'Z' }, { sourceId: 'b', model: 'A' }, { sourceId: 'a', model: 'M' }], weights: { 'a/Z': 3, 'b/A': 2 } }
const sources = [{ id: 'a', name: 'Alpha', baseUrl: '', protocol: '', authMode: '' }, { id: 'b', name: 'Beta', baseUrl: '', protocol: '', authMode: '' }]
function Harness({ onChange = vi.fn(), disabled = false }: { onChange?: (patch: Partial<CatalogModel>) => void; disabled?: boolean }) {
 const [model, setModel] = useState(initial)
 return <div className="tt-routing-editor"><AggregationMemberOrder model={model} sources={sources} pools={[]} disabled={disabled} onChange={patch => { onChange(patch); setModel(previous => ({ ...previous, ...patch })) }} /><output data-testid="weights">{JSON.stringify(model.weights)}</output></div>
}
const names = () => [...document.querySelectorAll('.tt-member-identity>strong')].map(node => node.textContent)
beforeEach(() => {
 window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
 class Pointer extends MouseEvent { pointerId: number; isPrimary: boolean; constructor(type: string, init: PointerEventInit) { super(type, init); this.pointerId = init.pointerId || 1; this.isPrimary = init.isPrimary ?? true } }
 vi.stubGlobal('PointerEvent', Pointer)
 vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1)); vi.stubGlobal('cancelAnimationFrame', vi.fn())
 HTMLElement.prototype.setPointerCapture = vi.fn(); HTMLElement.prototype.releasePointerCapture = vi.fn(); HTMLElement.prototype.hasPointerCapture = vi.fn(() => true)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
const geometry = () => {
 const rect = (top: number, height: number) => ({ top, bottom: top + height, left: 0, right: 500, width: 500, height, x: 0, y: top, toJSON: () => ({}) })
 vi.spyOn(document.querySelector('.tt-routing-editor')!, 'getBoundingClientRect').mockReturnValue(rect(0, 500))
 vi.spyOn(document.querySelector('.tt-routing-members')!, 'getBoundingClientRect').mockReturnValue(rect(40, 180))
 document.querySelectorAll<HTMLElement>('[data-member-key]').forEach((row, index) => vi.spyOn(row, 'getBoundingClientRect').mockReturnValue(rect(40 + index * 60, 60)))
}
it('moves the focused member with the keyboard and preserves identity-based weights', () => {
 render(<Harness />)
 const handle = screen.getByRole('button', { name: 'pool.dragMember Z' }); handle.focus()
 fireEvent.keyDown(handle, { key: 'End' })
 expect(names()).toEqual(['A', 'M', 'Z']); expect(document.activeElement).toBe(handle)
 expect(screen.getByTestId('weights').textContent).toBe(JSON.stringify(initial.weights))
 fireEvent.keyDown(handle, { key: 'Home' }); expect(names()).toEqual(['Z', 'A', 'M'])
 fireEvent.click(screen.getByRole('button', { name: 'pool.down Z' })); expect(names()).toEqual(['A', 'Z', 'M'])
})
it('commits pointer ordering only on drop, and does not mutate members on cancel or an outside drop', () => {
 const onChange = vi.fn(); render(<Harness onChange={onChange} />); geometry()
 const handle = screen.getByRole('button', { name: 'pool.dragMember Z' })
 fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 20, clientY: 70 })
 fireEvent.pointerMove(handle, { pointerId: 1, clientX: 20, clientY: 190 })
 expect(onChange).not.toHaveBeenCalled(); expect(document.querySelector('.is-drop-after')).toBeTruthy()
 fireEvent.pointerCancel(handle, { pointerId: 1 }); expect(names()).toEqual(['Z', 'A', 'M'])
 fireEvent.pointerDown(handle, { pointerId: 2, button: 0, clientX: 20, clientY: 70 })
 fireEvent.pointerMove(handle, { pointerId: 2, clientX: 20, clientY: 190 })
 fireEvent.pointerUp(handle, { pointerId: 2, clientX: 600, clientY: 190 }); expect(onChange).not.toHaveBeenCalled()
 fireEvent.pointerDown(handle, { pointerId: 3, button: 0, clientX: 20, clientY: 70 })
 fireEvent.pointerMove(handle, { pointerId: 3, clientX: 20, clientY: 190 })
 fireEvent.pointerUp(handle, { pointerId: 3, clientX: 20, clientY: 190 })
 expect(names()).toEqual(['A', 'M', 'Z']); expect(onChange).toHaveBeenCalledTimes(1)
 expect(screen.getByTestId('weights').textContent).toBe(JSON.stringify(initial.weights))
})
it('groups sources stably and offers alphabetical model ordering', async () => {
 render(<Harness />)
 fireEvent.click(screen.getByRole('button', { name: 'pool.organize' }))
 fireEvent.click(await screen.findByRole('menuitem', { name: 'pool.organize.source' }))
 expect(names()).toEqual(['Z', 'M', 'A'])
 fireEvent.click(screen.getByRole('button', { name: 'pool.organize' }))
 fireEvent.click(await screen.findByRole('menuitem', { name: 'pool.organize.model' }))
 expect(names()).toEqual(['A', 'M', 'Z'])
})
it('keeps order actions disabled during save', () => {
 render(<Harness disabled />)
 expect((screen.getByRole('button', { name: 'pool.dragMember Z' }) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByRole('button', { name: 'pool.organize' }) as HTMLButtonElement).disabled).toBe(true)
})
