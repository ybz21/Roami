export type ActivityEvent = { at: number; dialogues?: number; tasks?: number; commits?: number }
export type ActivityDay = { key: string; date: Date; count: number; dialogues: number; tasks: number; commits: number }
export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
export function activityCalendar(events: ActivityEvent[], now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const start = new Date(today); start.setDate(start.getDate() - 364)
  const counts = new Map<string, { dialogues: number; tasks: number; commits: number }>()
  for (const event of events) {
    const date = new Date(event.at * 1000)
    if (date < start || date > now) continue
    const key = dayKey(date), values = counts.get(key) || { dialogues: 0, tasks: 0, commits: 0 }
    values.dialogues += event.dialogues || 0; values.tasks += event.tasks || 0; values.commits += event.commits || 0
    counts.set(key, values)
  }
  const days: ActivityDay[] = []
  for (const date = new Date(start); date <= today; date.setDate(date.getDate() + 1)) {
    const key = dayKey(date), values = counts.get(key) || { dialogues: 0, tasks: 0, commits: 0 }
    days.push({ key, date: new Date(date), count: values.dialogues + values.tasks + values.commits, ...values })
  }
  let longest = 0, run = 0
  for (const day of days) { run = day.count ? run + 1 : 0; longest = Math.max(longest, run) }
  let current = 0, index = days.length - 1
  // Today's unfinished day does not break yesterday's streak.
  if (!days[index].count) index--
  for (; index >= 0 && days[index].count; index--) current++
  const padding = Array.from({ length: start.getDay() }, () => null)
  const cells: (ActivityDay | null)[] = [...padding, ...days]
  while (cells.length % 7) cells.push(null)
  const weeks = Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7))
  const totals = days.reduce((n, d) => ({ dialogues: n.dialogues + d.dialogues, tasks: n.tasks + d.tasks, commits: n.commits + d.commits }), { dialogues: 0, tasks: 0, commits: 0 })
  const positive = days.map((day) => day.count).filter((count) => count > 0).sort((a, b) => a - b)
  const thresholds = [0.25, 0.5, 0.75].map((q) => positive[Math.floor((positive.length - 1) * q)] || 0)
  return { days, weeks, totals, thresholds, total: totals.dialogues + totals.tasks + totals.commits, active: days.filter((d) => d.count > 0).length, current, longest }
}
export function activityLevel(count: number, thresholds: readonly number[]) { return count <= 0 ? 0 : count <= thresholds[0] ? 1 : count <= thresholds[1] ? 2 : count <= thresholds[2] ? 3 : 4 }
