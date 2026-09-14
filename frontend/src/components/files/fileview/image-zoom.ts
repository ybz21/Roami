// 图片预览的缩放算术。单独拎出来是因为这几条规则全是边界：图没加载完（naturalWidth=0）、
// 容器还没量到（clientHeight=0）、一像素的图标、一万像素的长截图——错一处的表现都是「白屏」
// 或「除以零得 Infinity 后 <img> 被要求画 Infinity px」。

export const MIN_SCALE = 0.05
export const MAX_SCALE = 8
/** 一次滚轮/一次点按的倍率。1.25 比 2 细，连点几下才到位，但不会一下越过想看的那一档。 */
export const ZOOM_STEP = 1.25

export type Size = { w: number; h: number }

export const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, Number.isFinite(s) ? s : 1))

/**
 * 适应窗口：**只缩不放**。小图放大到铺满只会糊，1:1 才是它的样子；
 * 尺寸还没量出来时返回 1，让它先按原始大小画一帧，量到了再收。
 */
export function fitScale(nat: Size, box: Size): number {
  if (!(nat.w > 0 && nat.h > 0 && box.w > 0 && box.h > 0)) return 1
  return clampScale(Math.min(1, box.w / nat.w, box.h / nat.h))
}

/** 按档缩放，并且总落在 [MIN, MAX] 内 */
export const zoomBy = (cur: number, dir: 1 | -1) => clampScale(dir > 0 ? cur * ZOOM_STEP : cur / ZOOM_STEP)

/** 滚轮/触控板的连续缩放：deltaY 越大缩得越多，方向与浏览器原生缩放一致（上滚放大） */
export const zoomByWheel = (cur: number, deltaY: number) => clampScale(cur * Math.exp(-deltaY / 300))

/**
 * 显示尺寸。向下取整而不是四舍五入：适应模式下往上凑的那半个像素会顶出一条滚动条，
 * 容器随之窄一点、重新适应、滚动条又消失——两个尺寸来回翻，ResizeObserver 跟着无限重渲。
 * 至少 1px：naturalWidth 还是 0 时别给 <img> 写 width:0。
 */
export const displaySize = (nat: Size, scale: number): Size => ({
  w: Math.max(1, Math.floor(nat.w * scale)),
  h: Math.max(1, Math.floor(nat.h * scale)),
})
