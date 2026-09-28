import type { GanttEngineer, GanttLunch, GanttTask, GanttTicket } from '../ganttTypes'
import type { PlanMoveResponse } from '../planApi'

/** Шаг, к которому прилипает время при перетаскивании. */
export const SNAP_MINUTES = 10

/** 545 → «9:05». Дробные минуты (время от планировщика) округляются. */
export function formatClock(value: number) {
  const rounded = Math.round(value)
  const hours = Math.floor(rounded / 60)
  const mins = rounded % 60
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
  /** Место в маршруте по окнам планировщика; без него backend встанет по времени. */
  position?: number
  /** Дорога к заявке, минуты, — по окну планировщика. */
  travel?: number
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
 * Зелёные ячейки по 10 минут: инженер → начало ячейки (минуты дня) → когда начать работу в ней.
 * Начало — внутри окна клиента, если получается, иначе самое раннее (тогда при постановке
 * спросим согласование с клиентом).
 */
export type FreeCells = Map<string, Map<number, number>>

function setCell(cells: FreeCells, engineerId: string, cell: number, start: number) {
  let row = cells.get(engineerId)
  if (!row) {
    row = new Map()
    cells.set(engineerId, row)
  }
  row.set(cell, start)
}

/** Приблизительные зелёные ячейки — без окон планировщика, по пересечениям на ленте. */
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
  const cells: FreeCells = new Map()
  for (const engineer of engineers) {
    for (let start = fromHour * 60; start < toHour * 60; start += SNAP_MINUTES) {
      const placement = evaluatePlacement({ ticket, engineer, start, tasks, now, movingId })
      if (placement.state === 'ok' || placement.state === 'approval') setCell(cells, engineer.id, start, start)
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

/** Окно постановки у инженера: начать работу можно с `earliest` по `latest` (минуты дня). */
export type EngineerSlot = {
  position: number
  earliest: number
  latest: number
  departure: number
  travel: number
}

/**
 * Куда можно поставить заявку — посчитано планировщиком по реальной дороге между адресами
 * (`GET /planning/plan/{id}/slots`). Во время перетаскивания проверка идёт только по ним.
 */
export type TicketSlots = {
  movable: boolean
  reason: string
  byEngineer: Map<string, EngineerSlot[]>
  refusals: Map<string, string>
}

const SLOT_EPS = 0.01

/** Визиты инженера, которые остаются на ленте, по времени. */
function laneOf(tasks: GanttTask[], engineerId: string, movingId?: string) {
  return tasks
    .filter((task) => task.engineerId === engineerId && task.id !== movingId && task.status !== 'cancelled')
    .sort((a, b) => a.start - b.start)
}

/**
 * Время прилипает к окну постановки: отпустили в 10 минутах от него — встаёт на ближайший край.
 * Узкое окно (меньше шага сетки) иначе не поймать.
 */
export function magnetStart(start: number, raw: number, slots: EngineerSlot[] | undefined) {
  if (!slots) return start
  if (slots.some((slot) => start >= slot.earliest - SLOT_EPS && start <= slot.latest + SLOT_EPS)) return start
  let best = start
  let distance = SNAP_MINUTES
  for (const slot of slots) {
    const low = Math.ceil(slot.earliest) <= slot.latest ? Math.ceil(slot.earliest) : slot.earliest
    const high = Math.floor(slot.latest) >= low ? Math.floor(slot.latest) : low
    const candidate = Math.min(Math.max(raw, low), high)
    const gap = Math.abs(candidate - raw)
    if (gap <= distance) {
      best = candidate
      distance = gap
    }
  }
  return best
}

/**
 * Проверка постановки по окнам планировщика: успеет ли инженер доехать, не сорвутся ли
 * следующие визиты и смена. Встать поверх назначенных — замена: её проверяет backend.
 */
export function evaluateBySlots({
  ticket,
  engineer,
  start,
  tasks,
  now,
  movingId,
  slots,
}: {
  ticket: GanttTicket
  engineer: GanttEngineer
  start: number
  tasks: GanttTask[]
  now: number
  movingId?: string
  slots: TicketSlots
}): Placement {
  const end = start + ticket.duration
  const base = { engineerId: engineer.id, start, end, displaced: [], outsideWindow: false }
  const invalid = (reason: string): Placement => ({ ...base, state: 'invalid', reason })

  if (!slots.movable) return invalid(slots.reason || 'Заявку уже не сдвинуть')
  const refusal = slots.refusals.get(engineer.id)
  if (refusal) return invalid(refusal.charAt(0).toUpperCase() + refusal.slice(1))
  if (start < now) return invalid('Это время уже прошло')

  const outsideWindow = start < ticket.windowFrom || start > ticket.windowTo
  const lane = laneOf(tasks, engineer.id, movingId)
  const implied = lane.filter((task) => task.start < start).length
  const list = slots.byEngineer.get(engineer.id) ?? []
  const fits = list.filter((slot) => start >= slot.earliest - SLOT_EPS && start <= slot.latest + SLOT_EPS)
  const slot = fits.find((item) => item.position === implied) ?? fits[0]
  if (slot) {
    return {
      ...base,
      outsideWindow,
      position: slot.position,
      travel: Math.round(slot.travel),
      state: outsideWindow ? 'approval' : 'ok',
    }
  }

  const overlaps = lane.filter((task) => task.start - task.travel < end && start < task.end)
  if (overlaps.some((task) => !isMovable(task))) return invalid('Пересекается с начатой заявкой')
  if (overlaps.length > 0) return { ...base, displaced: overlaps, outsideWindow, state: 'swap' }

  // Бросили на обед, а окна здесь нет: обеду некуда уехать (было бы куда — окно бы было)
  const lunch = engineer.lunch
  if (lunch && start < lunch.end && lunch.departure < end) {
    return invalid(`В это время обед ${formatRange(lunch.start, lunch.end)} — сдвинуть его некуда: соседние заявки не успеют`)
  }

  // На месте обеда окон два — до обеда и после; между ними обед подвинуть некуда
  const near = list.filter((item) => item.position === implied).sort((a, b) => a.earliest - b.earliest)
  if (near.length === 0) return invalid('Здесь не успеть доехать и выполнить работу')
  const first = near[0]!
  const last = near[near.length - 1]!
  if (start < first.earliest) return invalid(`Не успеет доехать: начать можно не раньше ${formatClock(first.earliest)}`)
  if (start > last.latest) return invalid(`Следующие заявки не успеют: начать нужно не позже ${formatClock(last.latest)}`)
  const after = near.find((item) => item.earliest > start) ?? last
  const before = [...near].reverse().find((item) => item.latest < start) ?? first
  return invalid(
    `В это время обед: до обеда начать можно не позже ${formatClock(before.latest)}, после — не раньше ${formatClock(after.earliest)}`,
  )
}

/** Обеды после хода по ответу backend: инженер → новый обед, null — обеда больше нет. */
export type LunchPatch = Map<string, Omit<GanttLunch, 'place'> | null>

export function lunchesOf(response: PlanMoveResponse | null | undefined): LunchPatch | undefined {
  if (!response?.ok || !response.lunches) return undefined
  const patch: LunchPatch = new Map(response.engineers.map((id) => [id, null]))
  for (const lunch of response.lunches) {
    patch.set(lunch.engineerId, {
      departure: lunch.departure,
      arrival: lunch.arrival,
      start: lunch.start,
      end: lunch.end,
    })
  }
  return patch
}

/** Обед на ленте — там, куда он уедет после хода; место обеда то же. */
export function withLunches(engineers: GanttEngineer[], patch: LunchPatch | undefined) {
  if (!patch || patch.size === 0) return engineers
  return engineers.map((engineer) => {
    if (!patch.has(engineer.id)) return engineer
    const next = patch.get(engineer.id)
    const place = engineer.lunch?.place ?? ''
    return { ...engineer, lunch: next ? { ...next, place } : null }
  })
}

/** Зелёные 10-минутные ячейки по окнам планировщика: ячейка зелёная, если начать в ней можно. */
export function findFreeCellsBySlots({
  ticket,
  engineers,
  now,
  fromHour,
  toHour,
  slots,
}: {
  ticket: GanttTicket
  engineers: GanttEngineer[]
  now: number
  fromHour: number
  toHour: number
  slots: TicketSlots
}) {
  const cells: FreeCells = new Map()
  if (!slots.movable) return cells
  const pick = (low: number, high: number) => (Math.ceil(low) <= high ? Math.ceil(low) : low)
  for (const engineer of engineers) {
    const list = slots.byEngineer.get(engineer.id)
    if (!list) continue
    for (let cell = fromHour * 60; cell < toHour * 60; cell += SNAP_MINUTES) {
      let fallback: number | null = null
      for (const slot of list) {
        const low = Math.max(cell, slot.earliest, now)
        const high = Math.min(cell + SNAP_MINUTES - 1, slot.latest)
        if (low > high) continue
        const inLow = Math.max(low, ticket.windowFrom)
        const inHigh = Math.min(high, ticket.windowTo)
        if (inLow <= inHigh) {
          fallback = pick(inLow, inHigh)
          break
        }
        fallback ??= pick(low, high)
      }
      if (fallback != null) setCell(cells, engineer.id, cell, fallback)
    }
  }
  return cells
}
