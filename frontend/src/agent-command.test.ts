import { describe, expect, it } from 'vitest'
import { agentCommand, agentLaunch } from './agent-command'
import type { Preferences } from './preferences'

const prefs = {
  claudeCommand: 'claude', codexCommand: 'codex',
  piCommand: '/opt/bin/pi', opencodeCommand: 'opencode',
} as Preferences

describe('agent launch command', () => {
  it('uses the configured executable for every agent', () => {
    expect(agentCommand('claude', prefs)).toBe('claude')
    expect(agentCommand('codex', prefs)).toBe('codex')
    expect(agentCommand('pi', prefs)).toBe('/opt/bin/pi')
    expect(agentCommand('opencode', prefs)).toBe('opencode')
  })

  it('keeps the initial task inside the interactive OpenCode session', () => {
    expect(agentLaunch('opencode', prefs, "fix John's bug")).toBe("opencode --prompt 'fix John'\\''s bug'")
    expect(agentLaunch('pi', prefs, 'fix it')).toBe("/opt/bin/pi 'fix it'")
  })
})
