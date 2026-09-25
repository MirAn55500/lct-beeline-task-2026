import type { CalendarDate } from '@internationalized/date'
import { getLocalTimeZone } from '@internationalized/date'

import { pluralRu } from './text'

const timeFormatter = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
})

const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const dayLabelFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  weekday: 'short',
})

export function formatTime(value: string | Date): string {
  const date = typeof value === 'string' ? new Date(value) : value
  return timeFormatter.format(date)
}

export function formatDateTime(value: string | Date): string {
  const date = typeof value === 'string' ? new Date(value) : value
  return dateTimeFormatter.format(date)
}

export function formatDayLabel(
  value: CalendarDate | Date,
  { weekday: withWeekday = true }: { weekday?: boolean } = {},
): string {
  const date =
    value instanceof Date ? value : value.toDate(getLocalTimeZone())
  const parts = dayLabelFormatter.formatToParts(date)
  const day = parts.find((part) => part.type === 'day')?.value ?? ''
  const month = parts.find((part) => part.type === 'month')?.value ?? ''
  const weekday = parts.find((part) => part.type === 'weekday')?.value ?? ''
  return withWeekday ? `${day} ${month}, ${weekday}` : `${day} ${month}`
}

/** Сколько ждать: «меньше минуты», «около 3 минут». */
export function formatWait(seconds: number): string {
  if (seconds < 45) return 'меньше минуты'
  const minutes = Math.max(1, Math.round(seconds / 60))
  return `около ${minutes} ${pluralRu(minutes, ['минуты', 'минут', 'минут'])}`
}

/** То же коротко, для шапки: «< 1 мин», «~3 мин». */
export function formatWaitShort(seconds: number): string {
  if (seconds < 45) return '< 1 мин'
  return `~${Math.max(1, Math.round(seconds / 60))} мин`
}
