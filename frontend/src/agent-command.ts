import type { AgentKind } from './agent-kind'
import type { Preferences } from './preferences'
import { shellQuote } from './shell-quote'

const COMMAND_KEYS = {
  claude: 'claudeCommand',
  codex: 'codexCommand',
  pi: 'piCommand',
  opencode: 'opencodeCommand',
} as const satisfies Record<AgentKind, keyof Preferences>

export function agentCommand(kind: AgentKind, prefs: Preferences): string {
  return prefs[COMMAND_KEYS[kind]]?.trim() || kind
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
  return `${cmd}${kind === 'opencode' ? ' --prompt' : ''} ${shellQuote(prompt)}`
}
