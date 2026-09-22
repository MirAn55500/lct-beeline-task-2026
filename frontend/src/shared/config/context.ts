import { parseDate, type CalendarDate } from '@internationalized/date'

export const REGIONS = ['Восток', 'Юго-восток', 'Юго-центр'] as const

export type Region = (typeof REGIONS)[number]

export const DEFAULT_REGION: Region = 'Восток'
export const DEFAULT_DATE = parseDate('2026-10-10')

const PLANNED_DATES = new Set([
  '2026-10-08',
  '2026-10-10',
  '2026-10-11',
  '2026-10-15',
])

export function hasPlannedDate(date: CalendarDate): boolean {
  return PLANNED_DATES.has(date.toString())
}
