import { beforeEach, expect, it, vi } from 'vitest'
import { loadSwarmDirectory } from './swarm-directory'
const test = vi.hoisted(() => ({ node: 'first', api: vi.fn() }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => test.api(...args) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => test.node + path }))
beforeEach(() => { test.node = 'first'; test.api.mockReset() })
it('shares concurrent directory reads and separates node scopes', async () => {
  const finish: ((value: { data: [] }) => void)[] = []
  test.api.mockImplementation(() => new Promise(resolve => finish.push(resolve)))
  const first = loadSwarmDirectory(), same = loadSwarmDirectory()
  expect(first).toBe(same)
  test.node = 'second'
  const other = loadSwarmDirectory()
  expect(other).not.toBe(first)
  expect(test.api).toHaveBeenCalledTimes(2)
  finish.forEach(resolve => resolve({ data: [] }))
  await Promise.all([first, same, other])
})
it('releases failed requests so recovery can read a new snapshot', async () => {
  test.api.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: [] })
  await expect(loadSwarmDirectory()).rejects.toThrow('offline')
  await expect(loadSwarmDirectory()).resolves.toEqual([])
  expect(test.api).toHaveBeenCalledTimes(2)
})
