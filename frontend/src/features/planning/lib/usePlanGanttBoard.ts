import { skipToken } from '@reduxjs/toolkit/query/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from '@heroui/react'

import type { GanttEngineer, GanttTask, GanttTicket, GanttUnassigned } from '../ganttTypes'
import { MOCK_GANTT_NOW, buildGantt, getGanttDataset, type GanttDataset } from '../mocks/gantt'
import {
  useGetPlanExportQuery,
  useGetPlanSlotsQuery,
  useMovePlanRequestMutation,
  type PlanMoveResponse,
  type PlanSlotsResponse,
} from '../planApi'
import {
  evaluateBySlots,
  evaluatePlacement,
  findFreeCells,
  findFreeCellsBySlots,
  formatClock,
  formatRange,
  magnetStart,
  type Placement,
  type TicketSlots,
} from './ganttPlacement'
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
    // Дорога — из окна планировщика; без него перенесённый визит везёт свою с собой.
    travel: placement.travel ?? ('travel' in origin ? origin.travel : 0),
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

/** Окна постановки из ответа backend — по заявке и инженеру. */
function indexSlots(response: PlanSlotsResponse | undefined) {
  if (!response) return null
  return new Map(
    response.requests.map((item): [string, TicketSlots] => [
      item.requestId,
      {
        movable: item.movable,
        reason: item.reason,
        byEngineer: new Map(
          Object.entries(item.slots).map(([engineerId, slots]) => [
            engineerId,
            slots.map(([position, earliest, latest, departure, travel]) => ({
              position,
              earliest,
              latest,
              departure,
              travel,
            })),
          ]),
        ),
        refusals: new Map(Object.entries(item.refusals)),
      },
    ]),
  )
}

const EMPTY: GanttDataset = { date: '', engineers: [], tasks: [], unassigned: [], ticketTypes: [], qualifications: {} }

/**
 * Состояние страницы Ганта. Визиты — из `/api/planning/plan`: выбранная в шапке версия плана,
 * без неё — последняя. Без плана на этот день лента пустая, как «Ganta — Empty».
 *
 * Ручные постановки проверяются по окнам планировщика (`/plan/{id}/slots`) — с дорогой между
 * адресами, без запросов во время перетаскивания; подтверждённый ход сохраняется новой версией
 * плана (`onSaved`). Если backend недоступен — моки и приблизительная проверка без дороги.
 */
export function usePlanGanttBoard(
  regionId: number | null,
  date: string,
  planId: number | null = null,
  /** `readOnly` — старая версия плана или прошедший день: заявки не перетаскиваются вовсе. */
  { onSaved, readOnly = false }: { onSaved?: (planId: number) => void; readOnly?: boolean } = {},
) {
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
  // Старые версии (до расписаний в БД) приходят без визитов и неназначенных.
  const noSchedule =
    plan != null &&
    plan.requests.length > 0 &&
    plan.routes.every((route) => route.visits.length === 0) &&
    plan.unassigned.length === 0
  const livePlanId = plan && !noSchedule ? plan.planId : null
  // Время идёт: к каким визитам уже выехали (их не сдвинуть) — перечитываем раз в минуту.
  const slotsQuery = useGetPlanSlotsQuery(livePlanId ?? skipToken, { pollingInterval: 60_000 })
  const slotIndex = useMemo(() => indexSlots(slotsQuery.currentData), [slotsQuery.currentData])
  const [moveRequest] = useMovePlanRequestMutation()
  const [saving, setSaving] = useState(false)
  // Какой план на ленте сейчас — ответ на сохранение мог прийти, когда уже открыт другой.
  const keyRef = useRef(key)
  useEffect(() => {
    keyRef.current = key
  }, [key])

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

  const moveArgs = (ticketId: string, placement: Placement, commit: boolean) => ({
    planId: livePlanId!,
    requestId: ticketId,
    engineerId: placement.engineerId,
    start: placement.start,
    ...(placement.position != null ? { position: placement.position } : {}),
    release: placement.displaced.map((task) => task.id),
    commit,
  })

  const commit = (next: GanttChange) => {
    const result = applyChange(tasks, unassigned, next, false)
    const previous = { tasks, unassigned }
    setTasks(result.tasks)
    setUnassigned(result.unassigned)
    setChange(null)
    setSelectedTicketId(null)
    if (livePlanId == null) return

    // Лента уже показывает ход; backend сохраняет его новой версией или отказывает — тогда откат.
    const committedKey = key
    const revert = () => {
      if (keyRef.current !== committedKey) return
      setTasks(previous.tasks)
      setUnassigned(previous.unassigned)
    }
    setSaving(true)
    moveRequest(moveArgs(next.ticketId, next.placement, true))
      .unwrap()
      .then((response) => {
        if (response.ok && response.planId != null) {
          toast.success(`План №${response.version} сохранён`, {
            description: `Заявка №${next.ticketId} — ${formatClock(next.placement.start)}`,
          })
          onSaved?.(response.planId)
          return
        }
        revert()
        toast.danger('Изменение не сохранено', { description: response.reason })
      })
      .catch(() => {
        revert()
        toast.danger('Не удалось сохранить изменение', { description: 'План остался без изменений' })
      })
      .finally(() => setSaving(false))
  }

  /** Проверка постановки: по окнам планировщика, пока их нет — приблизительная, без дороги. */
  const evaluate = (ticket: GanttTicket, engineer: GanttEngineer, start: number, movingId?: string) => {
    const slots = slotIndex?.get(ticket.id)
    return slots
      ? evaluateBySlots({ ticket, engineer, start, tasks, now, movingId, slots })
      : evaluatePlacement({ ticket, engineer, start, tasks, now, movingId })
  }

  /** Бросили заявку на ленту: сразу ставим или просим подтверждения. */
  const place = (ticketId: string, source: GanttChange['source'], placement: Placement) => {
    if (placement.state === 'invalid' || change || saving) return
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
    noSchedule,
    /** Идёт сохранение хода — новые ходы ждут. */
    saving,
    /** Проверки идут по окнам планировщика, а не приблизительно. */
    exact: slotIndex != null,
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
    evaluate,
    /**
     * Можно ли вообще взять заявку: backend отметил неподвижные — старая версия плана,
     * начатая или прошедшая работа. Пока окна не пришли — можно, проверит сам ход.
     */
    canDrag: (ticketId: string) => !readOnly && slotIndex?.get(ticketId)?.movable !== false,
    /** Время, прилипшее к ближайшему окну постановки у инженера. */
    magnet: (ticketId: string, engineerId: string, start: number, raw: number) =>
      magnetStart(start, raw, slotIndex?.get(ticketId)?.byEngineer.get(engineerId)),
    freeCells: (ticket: GanttTicket, fromHour: number, toHour: number, movingId?: string) => {
      const slots = slotIndex?.get(ticket.id)
      return slots
        ? findFreeCellsBySlots({ ticket, engineers: dataset.engineers, now, fromHour, toHour, slots })
        : findFreeCells({ ticket, engineers: dataset.engineers, tasks, now, movingId, fromHour, toHour })
    },
    /** Точная проверка хода backend-ом: новое расписание изменившихся маршрутов. */
    preview: (ticketId: string, placement: Placement): Promise<PlanMoveResponse | null> =>
      livePlanId == null
        ? Promise.resolve(null)
        : moveRequest(moveArgs(ticketId, placement, false))
            .unwrap()
            .catch(() => null),
  }
}

export type PlanGanttBoard = ReturnType<typeof usePlanGanttBoard>
