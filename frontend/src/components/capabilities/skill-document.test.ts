import { expect, it } from 'vitest'
import { skillDocument, skillFileText } from './skill-document'

it('separates folded metadata from the complete Markdown body', () => {
  const text = '\uFEFF---\r\nname: demo\r\ndescription: >-\r\n  Generate pages.\r\n  Preview results.\r\n---\r\n\r\n# Demo\r\n\r\n---\r\n\r\nExample'
  expect(skillDocument(text)).toEqual({ summary: 'Generate pages. Preview results.', body: '# Demo\n\n---\n\nExample' })
  expect(skillDocument(text, 'Publisher summary').summary).toBe('Publisher summary')
})

it('preserves a document without frontmatter', () => {
  expect(skillDocument('# Use it\n\n```yaml\nname: example\n```')).toEqual({ summary: '', body: '# Use it\n\n```yaml\nname: example\n```' })
})

it('decodes UTF-8 references while rejecting binary and invalid content', () => {
  expect(skillFileText('5L2g5aW9')).toBe('你好')
  expect(skillFileText('AP8=')).toBeNull()
  expect(skillFileText('/w==')).toBeNull()
  expect(skillFileText('invalid base64')).toBeNull()
})
