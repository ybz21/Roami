import { expect, it } from 'vitest'
import { parseCapability } from './capability-format'
it('reads CRLF and quoted frontmatter from external SKILL.md files', () => {
  expect(parseCapability('skills', '\uFEFF---\r\nname: "external-flow"\r\ndescription: \'A workflow\'\r\n---\r\n# Work')).toMatchObject({ name: 'external-flow', description: 'A workflow' })
})
it('rejects missing skill identity, JSON arrays and oversized uploads', () => {
  expect(() => parseCapability('skills', '# Instructions')).toThrow('SKILL_NAME_REQUIRED')
  expect(() => parseCapability('mcp', '[]')).toThrow('INVALID_CAPABILITY_IMPORT')
  expect(() => parseCapability('cli', 'x'.repeat(65537))).toThrow('CAPABILITY_IMPORT_TOO_LARGE')
})
it('preserves MCP batch configurations', () => {
  const config = { mcpServers: { fixture: { command: 'node', args: ['server.js'] } } }
  expect(parseCapability('mcp', JSON.stringify(config))).toEqual(config)
})

it('reads folded descriptions used by external skill packages', () => {
  expect(parseCapability('skills', '---\nname: external-workflow-instructions\ndescription: >-\n  First line\n  second line\n---\nInstructions')).toMatchObject({ name: 'external-workflow-instructions', description: 'First line second line' })
})
