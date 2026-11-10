import { describe, expect, it } from 'vitest'
import { processTree, type SessionProcess } from './SessionProcesses'

const process = (pid: number, ppid: number, rss = 0): SessionProcess => ({
  pid, ppid, rss, name: 'java', command: 'java', state: 'S', swap: 0, start: String(pid), protected: false,
})

describe('session process tree', () => {
  it('keeps detached daemons and places children below their parents', () => {
    const rows = processTree([process(30, 20, 100), process(20, 10), process(10, 1), process(40, 999, 200)])
    expect(rows.map(r => [r.process.pid, r.depth])).toEqual([[40, 0], [10, 0], [20, 1], [30, 2]])
  })
  it('keeps every process once when a racing snapshot contains a parent cycle', () => {
    const rows = processTree([process(10, 20), process(20, 10), process(30, 30)])
    expect(rows.map(r => r.process.pid).sort()).toEqual([10, 20, 30])
  })
})
