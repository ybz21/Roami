import { describe, expect, it } from 'vitest'
import { MAX_SCALE, MIN_SCALE, clampScale, displaySize, fitScale, zoomBy, zoomByWheel } from './image-zoom'

describe('fitScale', () => {
  it('长图按高收进容器', () => {
    // 900×1948 的手机长截图放进 1144×844 的预览栏：高度是瓶颈
    expect(fitScale({ w: 900, h: 1948 }, { w: 1144, h: 844 })).toBeCloseTo(844 / 1948, 5)
  })
  it('宽图按宽收进容器', () => {
    expect(fitScale({ w: 2000, h: 1188 }, { w: 1144, h: 844 })).toBeCloseTo(1144 / 2000, 5)
  })
  it('小图不放大——1:1 才是它的样子', () => {
    expect(fitScale({ w: 64, h: 64 }, { w: 1144, h: 844 })).toBe(1)
  })
  it('尺寸没量到时退回 1，不产生 0 或 Infinity', () => {
    expect(fitScale({ w: 0, h: 0 }, { w: 1144, h: 844 })).toBe(1)
    expect(fitScale({ w: 900, h: 1948 }, { w: 0, h: 0 })).toBe(1)
  })
  it('超长图也不会缩到 MIN 以下', () => {
    expect(fitScale({ w: 100, h: 400000 }, { w: 1000, h: 800 })).toBe(MIN_SCALE)
  })
})

describe('zoom', () => {
  it('按档进退且互为逆运算', () => {
    expect(zoomBy(zoomBy(1, 1), -1)).toBeCloseTo(1, 10)
  })
  it('顶到上下限就停住', () => {
    let s = 1
    for (let i = 0; i < 50; i++) s = zoomBy(s, 1)
    expect(s).toBe(MAX_SCALE)
    for (let i = 0; i < 100; i++) s = zoomBy(s, -1)
    expect(s).toBe(MIN_SCALE)
  })
  it('滚轮向上放大、向下缩小', () => {
    expect(zoomByWheel(1, -100)).toBeGreaterThan(1)
    expect(zoomByWheel(1, 100)).toBeLessThan(1)
  })
  it('clamp 吃得下 NaN', () => {
    expect(clampScale(Number.NaN)).toBe(1)
  })
})

describe('displaySize', () => {
  it('向下取整且至少 1px', () => {
    expect(displaySize({ w: 900, h: 1948 }, 0.4332)).toEqual({ w: 389, h: 843 })
    expect(displaySize({ w: 0, h: 0 }, 1)).toEqual({ w: 1, h: 1 })
  })
})
