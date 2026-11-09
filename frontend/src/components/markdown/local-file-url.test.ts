import { expect, it } from 'vitest'
import { localFileUrlPath } from './local-file-url'

it.each([
  ['file:///tmp/report.html', '/tmp/report.html'],
  ['file:///tmp/中文%20%23%3F%25.md#section', '/tmp/%E4%B8%AD%E6%96%87%20%23%3F%25.md#section'],
  ['file://localhost/home/ai/report.md', '/home/ai/report.md'],
])('normalizes local file URI %s without losing filename bytes', (href, expected) => {
  expect(localFileUrlPath(href)).toBe(expected)
})

it.each([
  'file://remote/home/ai/report.md', 'file:///tmp/report.md?private=1',
  'file:///tmp/%00report', 'file:///tmp/%2freport', 'file:///tmp/%5creport',
  'file:///tmp/%broken', 'file:///etc/passwd', 'file:///homework/report.md',
  'file:///tmp/a\\b', 'javascript:alert(1)', 'data:text/html,private',
  'https://example.com/report.md', '/api/file/tmp/report.md',
])('does not normalize unsupported URLs: %s', href => {
  expect(localFileUrlPath(href)).toBeUndefined()
})
