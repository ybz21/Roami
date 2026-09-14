// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { loadExpandedDirs, saveExpandedDirs } from './tree-expansion-memory'

const ROOT = '/home/ai/codes/ttmux'
const OTHER = '/home/ai/codes/other'

beforeEach(() => localStorage.clear())

describe('按根目录各记一份', () => {
  it('存了就取得回来', () => {
    saveExpandedDirs(ROOT, [`${ROOT}/frontend`, `${ROOT}/frontend/src`])
    expect(loadExpandedDirs(ROOT)).toEqual([`${ROOT}/frontend`, `${ROOT}/frontend/src`])
  })
  it('两个根互不干扰', () => {
    saveExpandedDirs(ROOT, [`${ROOT}/frontend`])
    saveExpandedDirs(OTHER, [`${OTHER}/src`])
    expect(loadExpandedDirs(ROOT)).toEqual([`${ROOT}/frontend`])
    expect(loadExpandedDirs(OTHER)).toEqual([`${OTHER}/src`])
  })
  it('没记过的根是空的（树就还是收着的一层）', () => {
    expect(loadExpandedDirs('/nope')).toEqual([])
  })
  it('空根不存也不取——路径条还没定下来时别往表里塞一条空键', () => {
    saveExpandedDirs('', ['/x'])
    expect(localStorage.getItem('roam.treeExpanded')).toBeNull()
    expect(loadExpandedDirs('')).toEqual([])
  })
  it('不在这个根底下的路径丢掉：目录被移走、换了机器都会留下这种垃圾', () => {
    localStorage.setItem('roam.treeExpanded', JSON.stringify({ [ROOT]: { dirs: [`${ROOT}/a`, '/elsewhere/b'], at: 1 } }))
    expect(loadExpandedDirs(ROOT)).toEqual([`${ROOT}/a`])
  })
  it('全收起来就把这个根删掉，不留空壳', () => {
    saveExpandedDirs(ROOT, [`${ROOT}/a`])
    saveExpandedDirs(ROOT, [])
    expect(loadExpandedDirs(ROOT)).toEqual([])
    expect(localStorage.getItem('roam.treeExpanded')).toBe('{}')
  })
  it('坏数据当没记过，不抛', () => {
    localStorage.setItem('roam.treeExpanded', '][')
    expect(loadExpandedDirs(ROOT)).toEqual([])
    expect(() => saveExpandedDirs(ROOT, [`${ROOT}/a`])).not.toThrow()
    expect(loadExpandedDirs(ROOT)).toEqual([`${ROOT}/a`])
  })
})

describe('别让它无限长', () => {
  it('一个根最多 300 条', () => {
    saveExpandedDirs(ROOT, Array.from({ length: 400 }, (_, i) => `${ROOT}/d${i}`))
    expect(loadExpandedDirs(ROOT)).toHaveLength(300)
  })
  it('根超过 12 个按最后用到的时间淘汰，刚写的那个一定留着', () => {
    for (let i = 0; i < 20; i++) saveExpandedDirs(`/r${i}`, [`/r${i}/a`])
    const all = JSON.parse(localStorage.getItem('roam.treeExpanded') || '{}')
    expect(Object.keys(all)).toHaveLength(12)
    expect(loadExpandedDirs('/r19')).toEqual(['/r19/a'])
    expect(loadExpandedDirs('/r0')).toEqual([])
  })
  it('同一毫秒内连写几次也不会把刚用过的根挤掉', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_000)
    for (let i = 0; i < 20; i++) saveExpandedDirs(`/r${i}`, [`/r${i}/a`])
    expect(loadExpandedDirs('/r19')).toEqual(['/r19/a'])
    expect(Object.keys(JSON.parse(localStorage.getItem('roam.treeExpanded') || '{}'))).toHaveLength(12)
    vi.restoreAllMocks()
  })
})
