import { Time } from '@internationalized/date'

/** Время смены: TimeField работает с Time, API — со строками «HH:MM:SS». */

export function formatTime(value: Time): string {
  return `${String(value.hour).padStart(2, '0')}:${String(value.minute).padStart(2, '0')}:00`
}

/** «09:00:00» из API → Time для TimeField. */
export function parseTime(value: string | null | undefined): Time | null {
  const match = /^(\d{1,2}):(\d{2})/.exec(value ?? '')
  return match ? new Time(Number(match[1]), Number(match[2])) : null
}
