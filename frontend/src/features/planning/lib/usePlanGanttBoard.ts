import { skipToken } from '@reduxjs/toolkit/query/react'
import { useMemo, useState } from 'react'

import type { GanttEngineer, GanttTask, GanttTicket, GanttUnassigned } from '../ganttTypes'
import { MOCK_GANTT_NOW, buildGantt, getGanttDataset, type GanttDataset } from '../mocks/gantt'
import { useGetPlanExportQuery } from '../planApi'
import { formatRange, type Placement } from './ganttPlacement'
import { isOfflineError } from './offline'

/**
 * Ручная постановка, которая ждёт подтверждения. Пока она висит, лента показывает
 * результат: заявка стоит на новом месте «Не назначена», снятые — в неназначенных.
 */
export type GanttChange = {
  ticketId: string
  /** Откуда взяли заявку: из неназначенных или с ленты. */
  source: 'unassigned' | 'task'
  placement: Placement
  /** swap — поповер «Подтвердите изменения», approve — окно согласования с клиентом. */
  step: 'swap' | 'approve'
}

/** Поля заявки, которые меняет «Управление заявкой». */
export type GanttTicketPatch = Partial<
  Pick<GanttTicket, 'typeLabel' | 'skill' | 'duration' | 'address' | 'windowFrom' | 'windowTo' | 'needsRouter' | 'needsBox'>
>

function pickTicket(item: GanttTicket): GanttTicket {
  return {
    id: item.id,
    typeLabel: item.typeLabel,
    address: item.address,
    skill: item.skill,
    windowFrom: item.windowFrom,
    windowTo: item.windowTo,
    duration: item.duration,
    needsRouter: item.needsRouter,
    needsBox: item.needsBox,
  }
}

function applyChange(
  tasks: GanttTask[],
  unassigned: GanttUnassigned[],
  change: GanttChange,
  draft: boolean,
) {
  const { placement, ticketId } = change
  const origin =
    change.source === 'task'
      ? tasks.find((task) => task.id === ticketId)
      : unassigned.find((ticket) => ticket.id === ticketId)
  if (!origin) return { tasks, unassigned }

  const ticket = pickTicket(origin)
  // Клиент согласился на новое время — окно прибытия переезжает вместе с заявкой.
  if (placement.outsideWindow && !draft) {
    ticket.windowTo = placement.start + (ticket.windowTo - ticket.windowFrom)
    ticket.windowFrom = placement.start
  }
  const placed: GanttTask = {
    ...ticket,
    engineerId: placement.engineerId,
    start: placement.start,
    end: placement.end,
    // Перенесённый визит везёт свою дорогу с собой; у новой заявки её посчитает планировщик.
    travel: 'travel' in origin ? origin.travel : 0,
    status: draft ? 'draft' : 'assigned',
  }

  const displacedIds = new Set(placement.displaced.map((task) => task.id))
  const released = placement.displaced.map(
    (task): GanttUnassigned => ({
      ...pickTicket(task),
      reason: 'manual',
      explanation: `Место заняла заявка №${ticket.id}. Прежнее время ${formatRange(task.windowFrom, task.windowTo)} больше не выполнить — согласуйте с клиентом новое.`,
      needsApproval: true,
    }),
  )

  return {
    tasks: [...tasks.filter((task) => task.id !== ticketId && !displacedIds.has(task.id)), placed],
    unassigned: [...released, ...unassigned.filter((item) => item.id !== ticketId)],
  }
}

const busyMinutes = (tasks: GanttTask[], engineerId: string) =>
  tasks.reduce((sum, task) => (task.engineerId === engineerId ? sum + task.duration : sum), 0)

/** «Сейчас» в минутах от полуночи дня плана: прошлый день — весь прошёл, будущий — ещё не начался. */
function nowFor(date: string) {
  const today = new Date()
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  if (date < iso) return 24 * 60
  if (date > iso) return -1
  return today.getHours() * 60 + today.getMinutes()
}

const EMPTY: GanttDataset = { date: '', engineers: [], tasks: [], unassigned: [], ticketTypes: [], qualifications: {} }

/**
 * Состояние страницы Ганта. Визиты — из `/api/planning/plan`: выбранная в шапке версия плана,
 * без неё — последняя. Без плана на этот день лента пустая, как «Ganta — Empty».
 * Если backend недоступен — моки. Ручные постановки пока локальные: мутации перепланирования в API ещё нет.
 */
export function usePlanGanttBoard(regionId: number | null, date: string, planId: number | null = null) {
  const query = useGetPlanExportQuery(regionId != null ? { regionId, date, planId } : skipToken)
  // 404 — плана на этот день нет; ошибка без статуса ответа — backend не поднят, остаёмся на моках.
  const offline = isOfflineError(query.isError, query.error)
  // Пока грузится другая версия, держим прежнюю ленту, а не мигаем пустой.
  const plan = query.currentData ?? (query.isFetching ? query.data : undefined)
  const now = plan ? nowFor(date) : MOCK_GANTT_NOW
  const dataset = useMemo(
    () => (plan ? buildGantt(plan, now) : offline ? getGanttDataset(regionId) : EMPTY),
    [plan, now, offline, regionId],
  )
  const hasPlan = plan ? true : offline && date === dataset.date
  const key = `${regionId}:${date}:${plan ? `plan-${plan.planId}` : offline ? 'mock' : 'none'}`

  const [loadedKey, setLoadedKey] = useState(key)
  const [tasks, setTasks] = useState<GanttTask[]>(() => (hasPlan ? dataset.tasks : []))
  const [unassigned, setUnassigned] = useState<GanttUnassigned[]>(() => (hasPlan ? dataset.unassigned : []))
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [change, setChange] = useState<GanttChange | null>(null)
  const [manageId, setManageId] = useState<string | null>(null)

  // Другой регион или день — другой план: сбрасываем всё прямо в рендере.
  if (loadedKey !== key) {
    setLoadedKey(key)
    setTasks(hasPlan ? dataset.tasks : [])
    setUnassigned(hasPlan ? dataset.unassigned : [])
    setSelectedTicketId(null)
    setChange(null)
    setManageId(null)
  }

  const view = change ? applyChange(tasks, unassigned, change, true) : { tasks, unassigned }

  // Загрузка — моковая: к проценту планировщика прибавляем разницу в минутах работ.
  const engineers = dataset.engineers.map((engineer): GanttEngineer => {
    if (!hasPlan) return { ...engineer, load: 0 }
    const shift = engineer.shifts.reduce((sum, [from, to]) => sum + to - from, 0) || 1
    const delta = busyMinutes(view.tasks, engineer.id) - busyMinutes(dataset.tasks, engineer.id)
    return { ...engineer, load: Math.max(0, Math.min(100, Math.round(engineer.load + (delta / shift) * 100))) }
  })

  const commit = (next: GanttChange) => {
    const result = applyChange(tasks, unassigned, next, false)
    setTasks(result.tasks)
    setUnassigned(result.unassigned)
    setChange(null)
    setSelectedTicketId(null)
  }

  /** Бросили заявку на ленту: сразу ставим или просим подтверждения. */
  const place = (ticketId: string, source: GanttChange['source'], placement: Placement) => {
    if (placement.state === 'invalid' || change) return
    const next: GanttChange = { ticketId, source, placement, step: 'swap' }
    if (placement.state === 'swap') setChange(next)
    else if (placement.outsideWindow) setChange({ ...next, step: 'approve' })
    else commit(next)
  }

  const confirmSwap = () => {
    if (!change) return
    if (change.placement.outsideWindow) setChange({ ...change, step: 'approve' })
    else commit(change)
  }

  const saveTicket = (ticketId: string, patch: GanttTicketPatch) => {
    setUnassigned((current) =>
      current.map((item) =>
        item.id === ticketId
          ? {
              ...item,
              ...patch,
              needsApproval: false,
              explanation: 'Новое время согласовано с клиентом — заявку можно поставить на ленту.',
            }
          : item,
      ),
    )
    setManageId(null)
  }

  return {
    date: dataset.date || date,
    hasPlan,
    isLoading: query.isFetching && !plan,
    // Старые версии (до расписаний в БД) приходят без визитов и неназначенных.
    noSchedule: plan != null && plan.requests.length > 0 && plan.routes.every((route) => route.visits.length === 0) && plan.unassigned.length === 0,
    now,
    engineers,
    tasks: view.tasks,
    unassigned: view.unassigned,
    ticketTypes: dataset.ticketTypes,
    qualifications: dataset.qualifications,
    selectedTicketId,
    change,
    manageTicket: unassigned.find((item) => item.id === manageId) ?? null,
    selectTicket: (ticketId: string | null) =>
      setSelectedTicketId((current) => (ticketId === current ? null : ticketId)),
    place,
    confirmSwap,
    confirmApproval: () => {
      if (change) commit(change)
    },
    cancelChange: () => setChange(null),
    openManage: (ticketId: string) => {
      setSelectedTicketId(null)
      setManageId(ticketId)
    },
    closeManage: () => setManageId(null),
    saveTicket,
  }
}

export type PlanGanttBoard = ReturnType<typeof usePlanGanttBoard>
