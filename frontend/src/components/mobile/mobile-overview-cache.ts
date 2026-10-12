import type { OverviewItem } from '../../session-overview'
export type { OverviewItem } from '../../session-overview'

let overview: OverviewItem[] | null = null

export function readMobileOverview(): OverviewItem[] | null {
  return overview
}

export function writeMobileOverview(items: OverviewItem[]): OverviewItem[] {
  overview = items
  return items
}
