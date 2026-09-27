/** Дни недели с понедельника, ISO-номера как в API. */
export const WEEKDAYS = [
  { day: 1, label: 'Пн' },
  { day: 2, label: 'Вт' },
  { day: 3, label: 'Ср' },
  { day: 4, label: 'Чт' },
  { day: 5, label: 'Пт' },
  { day: 6, label: 'Сб' },
  { day: 7, label: 'Вс' },
]

const LABEL = Object.fromEntries(WEEKDAYS.map(({ day, label }) => [day, label]))

/** [1, 2, 3, 5] → «Пн–Ср, Пт»: подряд идущие дни — диапазоном. */
function ranges(days: number[]): string {
  const parts: string[] = []
  let start = 0
  while (start < days.length) {
    let end = start
    while (end + 1 < days.length && days[end + 1] === days[end]! + 1) end += 1
    const from = LABEL[days[start]!]
    const to = LABEL[days[end]!]
    parts.push(end === start ? from! : end === start + 1 ? `${from}, ${to}` : `${from}–${to}`)
    start = end + 1
  }
  return parts.join(', ')
}

/** Рабочий график для карточки: «Пн–Пт» и «Сб–Вс выходной». */
export function describeWeekdays(workDays: number[]): { work: string; off: string | null } {
  const days = [...new Set(workDays)].filter((day) => day >= 1 && day <= 7).sort()
  if (days.length === 0) return { work: 'Нет рабочих дней', off: null }
  const off = WEEKDAYS.map(({ day }) => day).filter((day) => !days.includes(day))
  if (off.length === 0) return { work: 'Без выходных', off: null }
  return {
    work: ranges(days),
    off: `${ranges(off)} ${off.length === 1 ? 'выходной' : 'выходные'}`,
  }
}

export function sameDays(a: number[], b: number[]): boolean {
  const left = [...new Set(a)].sort()
  const right = [...new Set(b)].sort()
  return left.length === right.length && left.every((day, index) => day === right[index])
}
