// @vitest-environment jsdom
import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { gatewayDraft } from '../settings/local-model-gateway'
import type { GatewaySettingsController } from '../settings/gateway-settings'
import ModelUsageWorkspace from './ModelUsageWorkspace'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, args?: Record<string, string>) => args?.name ? `${key} ${args.name}` : args?.id ? `${key} ${args.id}` : key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../settings/model-usage-chart', () => ({ ModelUsageChart: ({ onSelect,points,series }: {onSelect:(key:string)=>void;points:{key:string;values:number[]}[];series:{label:string}[]}) => <><div data-testid="chart-data">{JSON.stringify({points,series})}</div><button type="button" onClick={()=>onSelect(points[0]?.key==='0'?'10':'2026-11-10')}>Select interval</button></> }))
const settings = { currency: 'USD', timezone: 'UTC', dailyLimit: 10, pricing: { default: { input_per_million: 1, output_per_million: 2, cache_read_per_million: 0.5 }, models: {} } }
const group = (sourceId: string, requests: number) => ({ day: '2026-11-12', sourceId, agentKind: 'codex', source: 'other', role: 'main', model: 'fixture', currency: 'USD', requests, inputTokens: requests * 100, outputTokens: requests * 10, cacheReadTokens: requests * 40, pending: 0, unknown: 0, usageUnknown: 0, failed: 0, cost: '1.000000000' })
const response = (path: string) => {
 const q = new URL(path, 'http://localhost').searchParams, audit = q.get('view') === 'audit'
 return { day: '2026-11-12', from: '2026-11-06', to: '2026-11-12', days: 7, timezone: 'UTC', today: [group('a', 30), group('b', 10)], groups: q.get('sourceId') ? [group(q.get('sourceId')!, 30)] : [group('a', 30), group('b', 10)], hourly: [group('a',30),group('b',10)].map(row=>({...row,hour:10})),hourlyDay:'2026-11-12', recent: audit ? [{ id: 'call-' + (q.get('page') || '1'), sourceId: 'a', agentKind: 'codex', source: 'other', model: 'fixture', role: 'main', state: 'unknown', currency: 'USD', cost: null, startedMs: Date.UTC(2026, 10, 12, 10), inputTokens: null, outputTokens: null, cacheReadTokens: null, priceStatus: 'unpriced', errorCode: 'MODEL_GATEWAY_PRICE_MISSING', httpStatus: 200, reconciliation: '' }] : [], options: { sources: ['a', 'b'], agents: ['codex'], models: ['fixture'] }, page: Number(q.get('page') || 1), pageSize: 20, total: audit ? 45 : 0, archived: 0, detailRetentionHours: 48 }
}
const controller = { saved: settings, draft: gatewayDraft(settings), usageVersion: 0, saving: false, error: '', notice: null, retry: vi.fn(), discard: vi.fn(), save: vi.fn(), setDraft: vi.fn(), openReconcile: vi.fn() } as unknown as GatewaySettingsController
function Harness() {
 const [mode, setMode] = useState<'overview' | 'audit'>('overview')
 return <><button type="button" onClick={() => setMode('overview')}>Overview test</button><button type="button" onClick={() => setMode('audit')}>Audit test</button><ModelUsageWorkspace mode={mode} controller={controller} sources={[{ id: 'a', name: 'Source A', baseUrl: '', protocol: 'openai-responses', authMode: 'api_key' }, { id: 'b', name: 'Source B', baseUrl: '', protocol: 'openai-responses', authMode: 'api_key' }]} onAudit={() => setMode('audit')} /></>
}
beforeEach(() => {
 vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
 window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
 vi.mocked(api).mockImplementation(async (_method, path) => ({ data: response(path) }))
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks() })
it('shows model requests without overview tables and sends the focused hour to audit',async()=>{
 const {container}=render(<Harness/>)
 await screen.findByTestId('chart-data')
 expect(container.querySelector('.model-usage-totals')?.textContent).toContain('4,400')
 expect(container.querySelectorAll('table')).toHaveLength(0)
 expect(screen.getByTestId('chart-data').textContent).toContain('fixture')
 fireEvent.mouseDown(screen.getByRole('combobox',{name:'modelUsage.groupBy'}))
 fireEvent.click(await screen.findByText('modelUsage.by.sourceId',{selector:'.ant-select-item-option-content'}))
 fireEvent.click(screen.getByRole('button',{name:'Source A 30'}))
 fireEvent.click(screen.getByRole('button',{name:'Select interval'}))
 fireEvent.click(screen.getByRole('button',{name:'modelUsage.openAudit'}))
 await screen.findByRole('button',{name:'modelUsage.inspectCall call-1'})
 expect(api).toHaveBeenCalledWith('GET',expect.stringMatching(/view=audit.*day=2026-11-12.*sourceId=a.*hour=10/),undefined,expect.anything())
 expect(container.querySelector('.model-usage-quota')).toBeNull()
 fireEvent.click(screen.getByText('modelUsage.breakdown',{selector:'summary'}))
 expect(container.querySelector('.model-usage-group-table')).toBeTruthy()
 fireEvent.click(container.querySelector('.ant-pagination-item-2')!)
 await screen.findByRole('button',{name:'modelUsage.inspectCall call-2'})
 fireEvent.click(screen.getByRole('button',{name:'modelUsage.inspectCall call-2'}))
 expect(screen.getByRole('heading',{name:'modelUsage.callDetail'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'common.back'}))
 fireEvent.click(screen.getByRole('button',{name:'Overview test'}))
 await screen.findByTestId('chart-data')
 expect(screen.getByRole('button',{name:'Source A 30'}).getAttribute('aria-pressed')).toBe('true')
 expect(container.querySelectorAll('table')).toHaveLength(0)
 expect(screen.getByRole('combobox',{name:'modelUsage.source'}).closest('.ant-select')?.textContent).toContain('modelUsage.allSources')
})
it('searches on the server and aborts the page request when unmounted', async () => {
 vi.mocked(api).mockImplementation(async (_method, path) => path.includes('q=client-request') ? await new Promise(() => {}) : { data: response(path) })
 const page = render(<Harness />)
 fireEvent.click(screen.getByRole('button', { name: 'Audit test' }))
 await screen.findByLabelText('modelUsage.search')
 const input = screen.getByLabelText('modelUsage.search')
 input.focus()
 fireEvent.change(input, { target: { value: 'client-request' } })
 await waitFor(() => expect(api).toHaveBeenCalledWith('GET', expect.stringContaining('q=client-request'), undefined, expect.anything()))
 expect(screen.getByLabelText('modelUsage.search')).toBe(input)
 expect(document.activeElement).toBe(input)
 const request = vi.mocked(api).mock.calls[vi.mocked(api).mock.calls.length - 1][3] as { signal: AbortSignal }
 page.unmount()
 expect(request.signal.aborted).toBe(true)
})

it('retains the chosen interval and group on returning from audit',async()=>{
 const {container}=render(<Harness/>)
 fireEvent.click(await screen.findByRole('button',{name:'Select interval'}))
 fireEvent.click(screen.getByRole('button',{name:'modelUsage.openAudit'}))
 await screen.findByRole('button',{name:'modelUsage.inspectCall call-1'})
 expect([...container.querySelectorAll<HTMLInputElement>('input[type=date]')].map(input=>input.value)).toEqual(['2026-11-12','2026-11-12'])
 expect(screen.getByText('modelUsage.custom').closest('.ant-segmented-item')?.classList.contains('ant-segmented-item-selected')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'Overview test'}))
 await screen.findByTestId('chart-data')
 expect(screen.getByRole('combobox',{name:'modelUsage.interval'}).closest('.ant-select')?.textContent).toContain('10:00')
})
