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
    expect(agentLaunch('opencode', prefs, "fix John's bug")).toBe("opencode --auto --prompt 'fix John'\\''s bug'")
    expect(agentLaunch('pi', prefs, 'fix it')).toBe("/opt/bin/pi 'fix it'")
  })

  it.each([
    ['claude', 'claude --dangerously-skip-permissions'],
    ['codex', 'codex --dangerously-bypass-approvals-and-sandbox'],
    ['opencode', 'opencode --auto'],
    ['pi', '/opt/bin/pi'],
  ] as const)('starts %s with automatic permissions, with or without a task', (kind, command) => {
    expect(agentLaunch(kind, prefs)).toBe(command)
    expect(agentLaunch(kind, prefs, 'fix it')).toBe(`${command}${kind === 'opencode' ? ' --prompt' : ''} 'fix it'`)
  })

  it.each([
    ['claude', 'claude --permission-mode auto'],
    ['claude', 'claude --permission-mode=plan'],
    ['claude', 'claude --dangerously-skip-permissions'],
    ['codex', 'codex --yolo'],
    ['codex', 'codex --full-auto'],
    ['codex', 'codex --dangerously-bypass-approvals-and-sandbox'],
    ['codex', 'codex -a on-request -s workspace-write'],
    ['opencode', 'opencode --auto'],
  ] as const)('preserves explicit modes in %s custom commands', (kind, command) => {
    expect(agentLaunch(kind, { ...prefs, [`${kind}Command`]: command })).toBe(command)
  })

  it('keeps custom executables and model arguments', () => {
    expect(agentLaunch('codex', { ...prefs, codexCommand: '/opt/codex --model configured' }, 'task')).toBe("/opt/codex --model configured --dangerously-bypass-approvals-and-sandbox 'task'")
  })
})
