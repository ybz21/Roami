import { expect, it } from 'vitest'
import zhCN from '../../i18n/locales/zh-CN'
import enUS from '../../i18n/locales/en-US'
import { marketError } from './market-error'

it.each([zhCN, enUS])('uses the structured error code ahead of a server message', dict => {
  const t = (key: string) => dict[key] || key
  const caught = Object.assign(new Error('Internal upstream message'), { apiError: { code: 'AGENT_RUNTIME_UNAVAILABLE' }, status: 503 })
  expect(marketError(caught, 'loadFailed', t)).toEqual({ message: t('capabilities.error.AGENT_RUNTIME_UNAVAILABLE'), diagnostic: 'AGENT_RUNTIME_UNAVAILABLE · HTTP 503' })
  expect(marketError(new Error('MARKET_RATE_LIMITED'), 'loadFailed', t).message).toBe(t('capabilities.error.MARKET_RATE_LIMITED'))
})

it('distinguishes connection errors and failed details without displaying raw server content', () => {
  const t = (key: string) => zhCN[key] || key
  expect(marketError(new TypeError('Failed to fetch'), 'loadFailed', t).message).toBe(t('capabilities.market.error.network'))
  expect(marketError(new Error('Internal details'), 'previewFailed', t).message).toBe(t('capabilities.market.error.previewFailed'))
  const caught = Object.assign(new Error('HTTP 502'), { apiError: { code: 'sensitive unstructured content' }, status: 502 })
  expect(marketError(caught, 'loadFailed', t)).toEqual({ message: t('capabilities.market.error.loadFailed'), diagnostic: 'HTTP 502' })
  expect(marketError(null, 'loadFailed', t).message).toBe(t('capabilities.market.error.loadFailed'))
})
