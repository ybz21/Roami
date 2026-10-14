import { describe, expect, it } from 'vitest'
import { activityCalendar, activityLevel, dayKey } from './activity-calendar'
const timestamp = (date: Date) => ({ at: date.getTime() / 1000, dialogues: 1 })
describe('activity calendar', () => {
  it('uses local calendar days across leap years and excludes future and expired commits', () => {
    const now = new Date(2024, 2, 1, 12)
    const result = activityCalendar([timestamp(new Date(2024, 1, 29, 23)), timestamp(new Date(2024, 2, 1, 10)), timestamp(new Date(2024, 2, 1, 13)), timestamp(new Date(2023, 2, 1))], now)
    expect(result.days).toHaveLength(365)
    expect(result.total).toBe(2)
    expect(result.active).toBe(2)
    expect(result.current).toBe(2)
    expect(result.days[result.days.length - 2]?.key).toBe('2024-02-29')
    expect(result.weeks.flat().filter(Boolean)).toHaveLength(365)
    expect(result.weeks.every((week) => week.length === 7)).toBe(true)
  })
  it('keeps yesterday’s streak until today ends and calculates the longest separately', () => {
    const now = new Date(2026, 9, 12, 12)
    const result = activityCalendar([8, 9, 10].map((day) => timestamp(new Date(2026, 9, day, 12))), now)
    expect(result.longest).toBe(3)
    expect(result.current).toBe(0)
    const yesterday = activityCalendar([10, 11].map((day) => timestamp(new Date(2026, 9, day, 12))), now)
    expect(yesterday.current).toBe(2)
    expect(dayKey(yesterday.days[yesterday.days.length - 1].date)).toBe('2026-10-12')
  })
  it('counts dialogues and tasks separately and includes historical commits in activity', () => {
    const now = new Date(2026, 9, 13, 12), at = now.getTime() / 1000
    const result = activityCalendar([{ at, dialogues: 3 }, { at, tasks: 2 }, { at, commits: 10 }], now)
    expect(result.totals).toEqual({ dialogues: 3, tasks: 2, commits: 10 })
    expect(result.total).toBe(15)
    expect(result.current).toBe(1)
    expect(activityCalendar([{ at, commits: 10 }], now).active).toBe(1)
  })
  it('handles an empty history and intensity thresholds', () => {
    const result = activityCalendar([], new Date(2026, 9, 12))
    expect([result.total, result.active, result.current, result.longest]).toEqual([0, 0, 0, 0])
    expect([0, 1, 2, 3, 5, 6, 9, 10].map(activityLevel)).toEqual([0, 1, 1, 2, 2, 3, 3, 4])
  })
})
