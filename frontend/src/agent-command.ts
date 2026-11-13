import { agentDefinition } from './agent-registry'
import type { AgentKind } from './agent-kind'
import type { Preferences } from './preferences'
import { shellQuote } from './shell-quote'

const COMMAND_KEYS: Partial<Record<string, keyof Preferences>> = {
  claude: 'claudeCommand',
  codex: 'codexCommand',
  pi: 'piCommand',
  opencode: 'opencodeCommand',
}

export function agentCommand(kind: AgentKind, prefs: Preferences, defaultCommand?: string): string {
  const key = COMMAND_KEYS[kind]
  return prefs.agentCommands?.[kind]?.trim() || (key ? String(prefs[key] || '').trim() : '') || defaultCommand || agentDefinition(kind)?.command || kind
}

export function agentLaunch(kind: AgentKind, prefs: Preferences, prompt?: string): string {
  let cmd = agentCommand(kind, prefs)
  // Explicit permission settings in custom commands remain authoritative.
  if (kind === 'claude' && !/(?:^|\s)--(?:permission-mode|dangerously-skip-permissions)(?:[=\s]|$)/.test(cmd)) {
    cmd += ' --dangerously-skip-permissions'
  } else if (kind === 'codex' && !/(?:^|\s)(?:--(?:dangerously-bypass-approvals-and-sandbox|yolo|full-auto|ask-for-approval|sandbox)|-[as])(?:[=\s]|$)/.test(cmd)) {
    cmd += ' --dangerously-bypass-approvals-and-sandbox'
  } else if (kind === 'opencode' && !/(?:^|\s)--auto(?:[=\s]|$)/.test(cmd)) {
    cmd += ' --auto'
  }
  if (!prompt) return cmd
  const flag = agentDefinition(kind)?.promptFlag || (kind === 'opencode' ? '--prompt' : '')
  return `${cmd}${flag ? ' ' + flag : ''} ${shellQuote(prompt)}`
}
