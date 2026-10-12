import { describe, expect, it } from 'vitest'
import { codexReconnectFailed, codexResumeCommand } from './codex-recovery'

describe('Codex reconnect failure', () => {
  it('recognizes the wrapped error shown in a narrow terminal', () => {
    expect(codexReconnectFailed('Automatic reconnect could not restore this\nsession. Your draft is still editable.\nServer connection could not be restored')).toBe(true)
  })

  it('ignores an old failure outside the visible tail', () => {
    expect(codexReconnectFailed('Reconnect failed - check the endpoint\n' + 'normal output\n'.repeat(25))).toBe(false)
  })
})

describe('Codex resume command', () => {
  it('resumes the linked conversation when its rollout is known', () => {
    expect(codexResumeCommand('/tmp/rollout-2026-10-12T18-00-00-12345678-1234-1234-1234-123456789abc.jsonl'))
      .toBe('codex resume 12345678-1234-1234-1234-123456789abc')
  })

  it('falls back to the most recent conversation only when no ID is known', () => {
    expect(codexResumeCommand()).toBe('codex resume --last')
  })
})
