// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { readMobileProjects, writeMobileProjects, type MobileProject } from './mobile-project-cache'

const projects: MobileProject[] = [{ key: 'roam', name: 'Roam', dir: '/codes/Roam', sessions: 1, unfinished: 0, worktrees: 1, lastActivity: 123 }]

describe('mobile project snapshot', () => {
  beforeEach(() => localStorage.clear())

  it('shows the last project list on the first render for the same node', () => {
    writeMobileProjects(projects, 'node-a')
    expect(readMobileProjects('node-a')).toEqual(projects)
    expect(readMobileProjects('node-b')).toBeNull()
  })

  it('discards old and invalid snapshots', () => {
    writeMobileProjects(projects, 'node-a')
    const all = JSON.parse(localStorage.getItem('roam.mobile.projects') || '{}')
    all['node-a'].at = Date.now() - 25 * 60 * 60 * 1000
    localStorage.setItem('roam.mobile.projects', JSON.stringify(all))
    expect(readMobileProjects('node-a')).toBeNull()
    localStorage.setItem('roam.mobile.projects', '{invalid')
    expect(readMobileProjects('node-a')).toBeNull()
  })
})
