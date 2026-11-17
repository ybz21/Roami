import { usePageEffect } from '../../../page-activity'
import { useState } from 'react'
import { nodeApi } from '../../cluster/node-url'
import { pollWhileVisible } from '../../../visible-poll'
import { loadSwarmDirectory } from '../../swarm/swarm-directory'
import type { Proj, ProjSwarm } from './project-model'

export function normDir(path: string): string { return String(path || '').trim().replace(/\/+/g, '/').replace(/\/+$/, '') }
export function swarmProjectMatches(target: { projectId?: string; directory?: string }, project: { key?: string; dir: string }): boolean {
  return target.projectId ? target.projectId === project.key : !!target.directory && normDir(project.dir) === normDir(target.directory)
}
export function useSwarmProjection(projects: Proj[]): ProjSwarm[] {
  const [swarms, setSwarms] = useState<ProjSwarm[]>([])
  const scope = nodeApi('/agent/swarms'), dirsKey = projects.map(project => `${project.key}\t${project.dir}\t${project.name}`).join('\n')
  usePageEffect(() => pollWhileVisible(async signal => {
    const groups = await loadSwarmDirectory()
    const result = groups.filter(group => !group.archived).flatMap(group => {
      const project = projects.find(item => swarmProjectMatches(group.target, item))
      return project ? [{ name: group.id, label: group.name, projKey: project.key, projName: project.name, total: group.work.length, inProj: group.work.length, pending: group.work.filter(item => ['blocked', 'waiting_user', 'failed', 'unknown'].includes(item.state)).length }] : []
    })
    if (!signal.aborted) setSwarms(result)
  }, 10000).stop, [dirsKey, scope])
  return swarms
}
