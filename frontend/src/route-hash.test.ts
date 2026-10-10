// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { normalizeRoute, readTermTokens } from './route-hash'

const at = (hash: string) => { location.hash = hash }

describe('readTermTokens：terms 的三态', () => {
  beforeEach(() => at('#/projects'))

  it('没写 terms = 这条链接对标签没意见（交给本机记忆）', () => {
    expect(readTermTokens()).toEqual({ terms: [], active: '', none: false })
  })
  it('terms=none = 明说这页不要标签', () => {
    at('#/browser?terms=none')
    expect(readTermTokens()).toEqual({ terms: [], active: '', none: true })
  })
  it('有值就还原那几个，none 不再成立', () => {
    at('#/projects?terms=a,b&active=b')
    expect(readTermTokens()).toEqual({ terms: ['a', 'b'], active: 'b', none: false })
  })
})

describe('legacy inbox links', () => {
  it('opens the project page for the old inbox root', () => {
    expect(normalizeRoute('inbox')).toBe('projects')
  })
  it('keeps session deep links for the app to open directly', () => {
    expect(normalizeRoute('inbox/session-a')).toBe('inbox/session-a')
  })
})
