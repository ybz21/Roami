// 上滚到接近顶部时自动往回翻一页。
//
// 用「上膛」位而不是计时器：一次触顶只加载一批。加载完内容插在头顶，
// 锚定会把滚动位置往下推，所以正常一页就自己离开了触发区；万一推得不够远，
// 没越过重上膛线也不会连着拉，用户还得再滚一下——这正好是想要的节奏。
export const EARLIER_EDGE = 120
export const EARLIER_REARM = 200

/** 滚动一次后的判定：load 为真表示这次该加载更早一页，armed 交给下一轮。 */
export function reachEarlierTop(armed: boolean, top: number, overflow: number): { armed: boolean; load: boolean } {
  if (top > EARLIER_REARM) return { armed: true, load: false }
  // overflow<=0：内容还没撑满一屏，用户根本没法往上滑，先让按钮顶着
  if (!armed || top > EARLIER_EDGE || overflow <= 0) return { armed, load: false }
  return { armed: false, load: true }
}
