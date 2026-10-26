// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { chargeText } from './model-charges'

it('formats the exact decimal receipt without converting it to a floating point amount', () => {
  const text = chargeText([{currency: 'USD', amount: '123456789.123456789012345678'}, {currency: 'CNY', amount: '0'}], 'en-US')
  expect(text).toMatch(/USD\s123,456,789\.123456789012345678/)
  expect(text).toMatch(/CNY\s0\.00/)
})
