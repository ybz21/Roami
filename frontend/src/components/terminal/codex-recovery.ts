export function codexReconnectFailed(screen: string): boolean {
  const tail = screen.split('\n').slice(-24).join(' ').replace(/\s+/g, ' ')
  return /Automatic reconnect could not restore this session|Server connection could not be restored|Reconnect failed\s*[—-]/i.test(tail)
}

export function codexResumeCommand(rollout?: string): string {
  const id = /-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$/i.exec(rollout || '')?.[1]
  return id ? `codex resume ${id}` : 'codex resume --last'
}
