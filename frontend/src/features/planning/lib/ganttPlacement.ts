import type { GanttEngineer, GanttTask, GanttTicket } from '../ganttTypes'

/** Шаг, к которому прилипает время при перетаскивании. */
export const SNAP_MINUTES = 10

/** 545 → «9:05». */
export function formatClock(value: number) {
  const hours = Math.floor(value / 60)
  const mins = value % 60
  return `${hours}:${String(mins).padStart(2, '0')}`
}

/** «17:00–20:00». */
export function formatRange(from: number, to: number) {
  return `${formatClock(from)}–${formatClock(to)}`
}

export function snapMinutes(value: number) {
  return Math.round(value / SNAP_MINUTES) * SNAP_MINUTES
}

/** Можно ли таскать визит: прошедшие, текущие и отменённые закреплены. */
export function isMovable(task: GanttTask) {
  return task.status === 'assigned'
}

export type PlacementState =
  /** Свободно и внутри окна клиента. */
  | 'ok'
  /** Свободно, но вне окна клиента — новое время надо согласовать. */
  | 'approval'
  /** Место занято назначенными заявками — их снимут, клиентам понадобится новое время. */
  | 'swap'
  /** Сюда нельзя. */
  | 'invalid'

export type Placement = {
  engineerId: string
  start: number
  end: number
  state: PlacementState
  /** Почему нельзя — для подсказки при перетаскивании. */
  reason?: string
  /** Назначенные заявки, которые освободят место. */
  displaced: GanttTask[]
  outsideWindow: boolean
}

const SKILL_LABEL: Record<string, string> = {
  connection: 'подключение',
  local: 'ремонт',
  emergency: 'аварии',
}

/**
 * Проверка ручной постановки заявки. Дорога стоящих визитов занята, как и работа,
 * а свою дорогу новая заявка не считает — это приблизительная подсказка для диспетчера,
 * окончательно план проверит планировщик.
 */
export function evaluatePlacement({
  ticket,
  engineer,
  start,
  tasks,
  now,
  movingId,
}: {
  ticket: GanttTicket
  engineer: GanttEngineer
  start: number
  tasks: GanttTask[]
  now: number
  /** Визит, который двигают, — с собой он не пересекается. */
  movingId?: string
}): Placement {
  const end = start + ticket.duration
  const base = { engineerId: engineer.id, start, end, displaced: [], outsideWindow: false }
  const invalid = (reason: string): Placement => ({ ...base, state: 'invalid', reason })

  if (!engineer.skills.includes(ticket.skill)) {
    return invalid(`Нет навыка: ${SKILL_LABEL[ticket.skill] ?? ticket.skill}`)
  }
  if (ticket.needsRouter && !engineer.equipment.includes('router')) return invalid('Нет роутера')
  if (ticket.needsBox && !engineer.equipment.includes('set_top_box')) return invalid('Нет приставки')
  if (start < now) return invalid('Это время уже прошло')
  if (!engineer.shifts.some(([from, to]) => start >= from && end <= to)) return invalid('Вне рабочей смены')

  const overlaps = tasks.filter(
    (task) =>
      task.engineerId === engineer.id &&
      task.id !== movingId &&
      task.status !== 'cancelled' &&
      task.start - task.travel < end &&
      start < task.end,
  )
  if (overlaps.some((task) => !isMovable(task))) return invalid('Пересекается с начатой заявкой')

  const outsideWindow = start < ticket.windowFrom || start > ticket.windowTo
  return {
    ...base,
    displaced: overlaps,
    outsideWindow,
    state: overlaps.length > 0 ? 'swap' : outsideWindow ? 'approval' : 'ok',
  }
}

/**
 * Часовые ячейки, где инженер свободен и подходит заявке, — зелёные в макете.
 * Ключ — `${engineerId}:${час}`, значение — начало в этом часе: внутри окна клиента, если получается,
 * иначе самое раннее свободное (тогда при постановке спросим согласование с клиентом).
 */
export function findFreeCells({
  ticket,
  engineers,
  tasks,
  now,
  movingId,
  fromHour,
  toHour,
}: {
  ticket: GanttTicket
  engineers: GanttEngineer[]
  tasks: GanttTask[]
  now: number
  movingId?: string
  fromHour: number
  toHour: number
}) {
  const cells = new Map<string, number>()
  for (const engineer of engineers) {
    for (let hour = fromHour; hour < toHour; hour += 1) {
      for (let start = hour * 60; start < (hour + 1) * 60; start += SNAP_MINUTES) {
        const placement = evaluatePlacement({ ticket, engineer, start, tasks, now, movingId })
        const key = `${engineer.id}:${hour}`
        if (placement.state === 'ok') {
          cells.set(key, start)
          break
        }
        if (placement.state === 'approval' && !cells.has(key)) cells.set(key, start)
      }
    }
  }
  return cells
}

/** «1 приставка, 2 роутера» — снаряжение заявки; пусто, если ничего не нужно. */
export function equipmentLabel(ticket: Pick<GanttTicket, 'needsRouter' | 'needsBox'>) {
  const parts = []
  if (ticket.needsBox) parts.push('1 приставка')
  if (ticket.needsRouter) parts.push('1 роутер')
  return parts.join(', ')
}
