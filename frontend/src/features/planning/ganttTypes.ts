/** Типы страницы «План работ → Гант». Время везде — минуты от полуночи дня плана в поясе региона. */

import type { MapEngineer, UnassignedReason } from './mapTypes'

/**
 * Состояние визита на ленте. Цвета и подписи — как у Ganta-card в макете:
 * серые прошедшие, оранжевые текущие, жёлтые будущие, белые отменённые.
 */
export type GanttStatus =
  | 'done'
  | 'working'
  | 'onWay'
  | 'assigned'
  | 'cancelled'
  /** Поставлена вручную и ждёт подтверждения — «Не назначена». */
  | 'draft'

export type GanttTicket = {
  /** Номер заявки из БК. */
  id: string
  /** Короткий тип для карточки: «Подключение», «Ремонт», «Авария»… */
  typeLabel: string
  address: string
  /** Навык планировщика: connection, local, emergency. */
  skill: string
  /** Окно прибытия клиента: работа должна начаться внутри него. */
  windowFrom: number
  windowTo: number
  /** Длительность работ на адресе без дороги. */
  duration: number
  needsRouter: boolean
  needsBox: boolean
}

export type GanttTask = GanttTicket & {
  engineerId: string
  /** Работа на адресе. */
  start: number
  end: number
  /** Дорога до адреса перед работой, минуты: участок плашки от выезда до начала работ. */
  travel: number
  status: GanttStatus
}

export type GanttUnassigned = GanttTicket & {
  reason: UnassignedReason
  /** Объяснение планировщика — в подсказке на теге причины. */
  explanation: string
  /**
   * Снята с маршрута при замене: прежнее время клиента уже не выполнить,
   * нужно согласовать новое — красная карточка с тегом «Согласовать с клиентом».
   */
  needsApproval?: boolean
}

export type GanttEngineer = MapEngineer & {
  skills: string[]
  /** Снаряжение из профиля: router, set_top_box. */
  equipment: string[]
  /** Рабочие интервалы смены, между ними — перерыв. */
  shifts: [number, number][]
}

/** Контакт клиента для согласования нового времени. */
export type ClientContact = {
  name: string
  phone: string
}
