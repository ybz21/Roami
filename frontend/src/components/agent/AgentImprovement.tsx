import RsiWorkspace from './RsiWorkspace'

export default function AgentImprovement({ node, runId, onRun }: { node: string | null; workflow?: boolean; runId?: string; onRun?: (id: string) => void }) {
  return <RsiWorkspace key={node ?? 'local'} node={node} runId={runId} onRun={onRun} />
}
