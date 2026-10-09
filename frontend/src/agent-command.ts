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
  const cmd = agentCommand(kind, prefs)
  if (!prompt) return cmd
  return `${cmd}${kind === 'opencode' ? ' --prompt' : ''} ${shellQuote(prompt)}`
}
