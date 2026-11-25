export function taskNameFromPrompt(p: string, limit = 16): string {
  const first = (p.trim().split(/\n/)[0] || '').replace(/["'`«»""'']/g, '').trim()
  const lead = first.replace(/^(?:请|麻烦|帮我|帮忙|你去|你来|你先|你把|你|我要|我想|我们|给我|来|去)+\s*/, '')
  const seg = (lead || first).split(/[，。,.!！？?;；:：]/)[0]
  const base = seg.length >= 4 ? seg : (lead || first)
  let cut = base.slice(0, limit)
  if (base.length > limit) {
    // 切点落在拉丁词/数字中间 → 退回上一个边界，别留半个词（Spar…、5.…）
    if (/[A-Za-z0-9.]/.test(base[limit - 1]) && /[A-Za-z0-9.]/.test(base[limit])) {
      const back = cut.replace(/[A-Za-z0-9.]+$/, '')
      if (back.trim().length >= 4) cut = back
    }
    // 末尾剩一个孤零零的汉字，多半是被切成两半的词（「论坛」→「论」）：丢掉
    const lone = cut.replace(/[\s]([\u4e00-\u9fff])$/, '')
    if (lone.trim().length >= 4) cut = lone
  }
  return cut.trim().replace(/[-，。,.!！？?;；:：\s]+$/g, '').replace(/\s+/g, '-')
}
