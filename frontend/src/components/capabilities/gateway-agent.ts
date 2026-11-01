export const gatewayAgentNames: Record<string, string> = { opencode: 'OpenCode', claude: 'Claude Code', codex: 'Codex', pi: 'Pi', roami: 'Roami' }
export type GatewayAgentKey = { pending?: boolean; agentKind: string; keyId: string; suffix: string; disabled: boolean; connected: boolean; configRevision: string; configChanged: boolean; unavailable: boolean; updatedMs: number }
