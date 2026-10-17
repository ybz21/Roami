import { describe, expect, it } from 'vitest'
import { fileLink } from './file-link'

const parse = (href: string) => fileLink(href, 'https://roami.test', '/api/file/raw')

describe('mobile file links', () => {
  it('decodes query paths without losing special characters', () => {
    expect(parse('/api/file/raw?path=%2Ftmp%2F%E9%A2%84%E8%A7%88%20%2B%25.html')).toMatchObject({ path: '/tmp/预览 +%.html', name: '预览 +%.html' })
  })
  it('keeps appended paths and node prefixes intact', () => {
    for (const href of ['/api/file/tmp/a.html', '/api/file/raw/tmp/a.html', '/api/file/serve/tmp/a.html', '/n/other/api/file/raw?path=%2Ftmp%2Fa.html']) {
      expect(parse(href)).toEqual({ url: 'https://roami.test' + href, name: 'a.html', path: undefined, resolvePath: !href.startsWith('/n/') })
    }
  })
  it('keeps relative paths for server resolution', () => {
    expect(parse('/api/file/raw?path=docs/readme.md')?.path).toBeUndefined()
    expect(parse('/api/file/docs/readme.md')?.name).toBe('readme.md')
  })
  it('leaves downloads, external links and invalid URLs to normal navigation', () => {
    for (const href of ['/api/file/raw?path=%2Fa&dl=1', 'https://other.test/api/file/raw?path=%2Fa', '/api/files', 'mailto:a@example.com', 'http://[', '/api/file/%ZZ']) expect(parse(href)).toBeNull()
  })
})
