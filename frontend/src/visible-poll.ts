/** One request at a time; hidden pages resume with a fresh snapshot. */
export function pollWhileVisible(load: (signal: AbortSignal) => Promise<unknown>, interval: number) {
  let stopped = false, failures = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let deadline: ReturnType<typeof setTimeout> | undefined
  let pending: AbortController | undefined

  const cancel = () => {
    clearTimeout(timer)
    clearTimeout(deadline)
    pending?.abort()
    pending = undefined
  }
  const tick = async () => {
    if (stopped || document.hidden || pending) return
    clearTimeout(timer)
    const controller = new AbortController()
    pending = controller
    const timeout = setTimeout(() => controller.abort(), 15_000)
    deadline = timeout
    try {
      await load(controller.signal)
      if (pending === controller) failures = controller.signal.aborted ? failures + 1 : 0
    } catch {
      if (pending === controller) failures++
      controller.abort()
    } finally {
      clearTimeout(timeout)
      if (pending === controller) {
        pending = undefined
        deadline = undefined
        if (!stopped && !document.hidden) timer = setTimeout(tick, Math.min(interval * 2 ** failures, 60_000))
      }
    }
  }
  const visibility = () => { if (document.hidden) cancel(); else void tick() }
  document.addEventListener('visibilitychange', visibility)
  void tick()
  return {
    refresh: tick,
    stop: () => { stopped = true; cancel(); document.removeEventListener('visibilitychange', visibility) },
  }
}
