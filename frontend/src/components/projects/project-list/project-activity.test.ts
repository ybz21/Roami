import { describe, expect, it } from 'vitest'
import type { OverviewItem } from '../../../session-overview'
import type { Proj } from './project-model'
import { mergeProjectActivity } from './project-activity'

const project = {
  key: 'project', name: 'project', dir: '/project', git: true, pinned: false,
  sessions: 3, attached: 0, worktrees: 1, unfinished: 0, cleanable: 0, races: 0,
  lastActivity: 0, firstSeen: 0, running: 0, waiting: 0,
  top: [{ name: 'pi', label: 'Pi work', attached: false, running: false, waiting: false, lastActivity: 1 }],
} satisfies Proj

const item = (name: string, values: Partial<OverviewItem>): OverviewItem => ({
  name, label: name, lastActivity: 1, dormant: false, projectKey: 'project',
  agent: 'pi', running: false, waiting: false, ...values,
})

describe('project activity from the shared session overview', () => {
  it('counts CLI agents beyond the card preview and updates the visible row', () => {
    const [merged] = mergeProjectActivity([project], [
      item('pi', { running: true }), item('opencode', { agent: 'opencode', running: true }),
      item('waiting', { waiting: true, running: false }),
    ])
    expect(merged.running).toBe(2)
    expect(merged.waiting).toBe(1)
    expect(merged.top?.[0]).toMatchObject({ name: 'pi', running: true, agent: 'pi' })
    expect(merged.needs?.map((session) => session.name)).toEqual(['waiting'])
  })

  it('keeps project data when the overview request is unavailable', () => {
    expect(mergeProjectActivity([project], null)).toEqual([project])
  })
})
