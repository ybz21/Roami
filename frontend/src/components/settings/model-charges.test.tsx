// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { chargeText, ModelCharges } from './model-charges'

it('formats the exact decimal receipt without converting it to a floating point amount', () => {
  const text = chargeText([{currency: 'USD', amount: '123456789.123456789012345678'}, {currency: 'CNY', amount: '0'}], 'en-US')
  expect(text).toMatch(/USD\s123,456,789\.123456789012345678/)
  expect(text).toMatch(/CNY\s0\.00/)
})

vi.mock('../../i18n',()=>({useI18n:()=>({locale:'en-US',t:(key:string,values?:Record<string,string>)=>key+(values?.amount?' '+values.amount:'')})}))
afterEach(cleanup)

it('labels a pure local estimate including free configured calls',()=>{
  const local=[{currency:'USD',amount:'0'}]
  render(<ModelCharges charges={local} localCharges={local} estimatedCharges={[]} />)
  expect(screen.getByText(/agent.proxy.localEstimateAmount.*USD.*0.00/)).toBeTruthy()
  expect(screen.queryByText(/agent.proxy.includesLocalEstimate/)).toBeNull()
  expect(screen.queryByText('agent.proxy.costUnknown')).toBeNull()
})

it('shows combined fees with the estimated portion and keeps historical estimates separate',()=>{
  render(<ModelCharges charges={[{currency:'USD',amount:'0.3'}]} localCharges={[{currency:'USD',amount:'0.2'}]} estimatedCharges={[{currency:'CNY',amount:'9'}]} />)
  expect(screen.getByText(/USD.*0.30/)).toBeTruthy()
  expect(screen.getByText(/agent.proxy.includesLocalEstimate.*USD.*0.20/)).toBeTruthy()
  expect(screen.getByText(/agent.proxy.historicalEstimate.*CNY.*9.00/)).toBeTruthy()
})
