import { describe, expect, it } from 'vitest'
import { EARLIER_EDGE, EARLIER_REARM, reachEarlierTop } from './earlier-autoload'

describe('上滚自动翻更早一页', () => {
  it('触顶加载一次，停在那儿不会连着拉', () => {
    let armed = true
    const hit = (top: number, overflow = 1200) => {
      const next = reachEarlierTop(armed, top, overflow)
      armed = next.armed
      return next.load
    }
    expect(hit(0)).toBe(true)
    expect(hit(0)).toBe(false)
    expect(hit(EARLIER_EDGE)).toBe(false)
  })

  it('滚下来越过重上膛线之后，再触顶又能加载', () => {
    let armed = true
    const hit = (top: number) => {
      const next = reachEarlierTop(armed, top, 1200)
      armed = next.armed
      return next.load
    }
    expect(hit(0)).toBe(true)
    expect(hit(EARLIER_REARM + 1)).toBe(false)
    expect(hit(EARLIER_EDGE - 1)).toBe(true)
    // 重上膛线以内来回不算：那只是锚定之后落点离顶不远，不该自动再拉一批
    expect(hit(EARLIER_REARM - 1)).toBe(false)
    expect(hit(EARLIER_EDGE - 1)).toBe(false)
  })

  it('内容没撑满一屏时不自动加载', () => {
    expect(reachEarlierTop(true, 0, 0)).toEqual({ armed: true, load: false })
  })
})
