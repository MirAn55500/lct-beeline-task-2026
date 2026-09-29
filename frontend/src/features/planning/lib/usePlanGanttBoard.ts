import { skipToken } from '@reduxjs/toolkit/query/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from '@heroui/react'

import type { GanttEngineer, GanttTask, GanttTicket, GanttUnassigned } from '../ganttTypes'
import { MOCK_GANTT_NOW, buildGantt, getGanttDataset, type GanttDataset } from '../mocks/gantt'
import {
  useGetPlanExportQuery,
  useGetPlanSlotsQuery,
  useMovePlanBatchMutation,
  useMovePlanRequestMutation,
  type PlanMoveItem,
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
  lunchesOf,
  magnetStart,
  withLunches,
  type LunchPatch,
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
  /** Куда уедут обеды — по превью хода; пока ход висит, лента показывает их там. */
  lunches?: LunchPatch
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

function toMoveItem(ticketId: string, placement: Placement): PlanMoveItem {
  return {
    requestId: ticketId,
    engineerId: placement.engineerId,
    start: placement.start,
    ...(placement.position != null ? { position: placement.position } : {}),
    release: placement.displaced.map((task) => task.id),
  }
}

const EMPTY: GanttDataset = { date: '', engineers: [], tasks: [], unassigned: [], ticketTypes: [], qualifications: {} }

/**
 * Состояние страницы Ганта. Визиты — из `/api/planning/plan`: выбранная в шапке версия плана,
 * без неё — последняя. Без версии плана backend отдаёт каркас дня: инженеры и заявки без
 * визитов (как «Ganta — Empty»), а не 404.
 *
 * Ручные постановки копятся локально (черновик): превью — `/plan/{id}/move` или пакет
 * `/plan/{id}/moves` с commit=false; «Сохранить» отправляет все ходы разом и создаёт одну
 * новую версию. «Сбросить» и уход со страницы возвращают исходный план.
 */
export function usePlanGanttBoard(
  regionId: number | null,
  date: string,
  planId: number | null = null,
  /** `readOnly` — старая версия плана или прошедший день: заявки не перетаскиваются вовсе. */
  { onSaved, readOnly = false }: { onSaved?: (planId: number) => void; readOnly?: boolean } = {},
) {
  const query = useGetPlanExportQuery(regionId != null ? { regionId, date, planId } : skipToken, {
    // После загрузки заявок кэш пустого дня иначе остаётся при возврате на Гант.
    refetchOnMountOrArgChange: true,
  })
  // Ошибка без статуса ответа — backend не поднят, остаёмся на моках.
  const offline = isOfflineError(query.isError, query.error)
  // Пока грузится другая версия, держим прежнюю ленту, а не мигаем пустой.
  const plan = query.currentData ?? (query.isFetching ? query.data : undefined)
  const now = plan ? nowFor(date) : MOCK_GANTT_NOW
  const dataset = useMemo(
    () => (plan ? buildGantt(plan, now) : offline ? getGanttDataset(regionId) : EMPTY),
    [plan, now, offline, regionId],
  )
  // Версия плана есть только при planId > 0; 0 — каркас дня без назначений.
  const hasPlan = plan != null ? plan.planId > 0 : offline && date === dataset.date
  const key = `${regionId}:${date}:${plan ? `plan-${plan.planId}` : offline ? 'mock' : 'none'}`
  // Старые версии (до расписаний в БД) приходят без визитов и неназначенных.
  const noSchedule =
    plan != null &&
    plan.planId > 0 &&
    plan.requests.length > 0 &&
    plan.routes.every((route) => route.visits.length === 0) &&
    plan.unassigned.length === 0
  const livePlanId = plan && plan.planId > 0 && !noSchedule ? plan.planId : null
  // Время идёт: к каким визитам уже выехали (их не сдвинуть) — перечитываем раз в минуту.
  const slotsQuery = useGetPlanSlotsQuery(livePlanId ?? skipToken, { pollingInterval: 60_000 })
  const slotIndex = useMemo(() => indexSlots(slotsQuery.currentData), [slotsQuery.currentData])
  const [moveRequest] = useMovePlanRequestMutation()
  const [moveBatch] = useMovePlanBatchMutation()
  const [saving, setSaving] = useState(false)
  // Какой план на ленте сейчас — ответ на сохранение мог прийти, когда уже открыт другой.
  const keyRef = useRef(key)
  useEffect(() => {
    keyRef.current = key
  }, [key])

  const [loadedKey, setLoadedKey] = useState(key)
  const [tasks, setTasks] = useState<GanttTask[]>(() => dataset.tasks)
  const [unassigned, setUnassigned] = useState<GanttUnassigned[]>(() => dataset.unassigned)
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [change, setChange] = useState<GanttChange | null>(null)
  const [manageId, setManageId] = useState<string | null>(null)
  // Обеды после локального хода — пока не сохранили / не сбросили
  const [lunches, setLunches] = useState<LunchPatch | undefined>(undefined)
  // Подтверждённые ходы, ещё не отправленные на backend одной новой версией.
  const [pendingMoves, setPendingMoves] = useState<PlanMoveItem[]>([])
  const pendingRef = useRef(pendingMoves)
  useEffect(() => {
    pendingRef.current = pendingMoves
  }, [pendingMoves])
  // useBlocker читает это синхронно: setState ещё не успел перерисовать, а setPlanId уже меняет URL.
  const dirtyRef = useRef(false)

  // Другой регион или день — другой план: сбрасываем всё прямо в рендере.
  if (loadedKey !== key) {
    setLoadedKey(key)
    setTasks(dataset.tasks)
    setUnassigned(dataset.unassigned)
    setSelectedTicketId(null)
    setChange(null)
    setManageId(null)
    setLunches(undefined)
    setPendingMoves([])
    dirtyRef.current = false
  }

  const dirty = pendingMoves.length > 0
  dirtyRef.current = dirty
  const view = change ? applyChange(tasks, unassigned, change, true) : { tasks, unassigned }

  // Загрузка — моковая: к проценту планировщика прибавляем разницу в минутах работ.
  const lunchPatch = change?.lunches ?? lunches
  const engineers = withLunches(dataset.engineers, lunchPatch).map((engineer): GanttEngineer => {
    if (!hasPlan) return { ...engineer, load: 0 }
    const shift = engineer.shifts.reduce((sum, [from, to]) => sum + to - from, 0) || 1
    const delta = busyMinutes(view.tasks, engineer.id) - busyMinutes(dataset.tasks, engineer.id)
    return { ...engineer, load: Math.max(0, Math.min(100, Math.round(engineer.load + (delta / shift) * 100))) }
  })

  const moveArgs = (ticketId: string, placement: Placement, commit: boolean) => ({
    planId: livePlanId!,
    ...toMoveItem(ticketId, placement),
    commit,
  })

  /** Локально применяет ход — на backend уйдёт только по «Сохранить». */
  const commit = (next: GanttChange) => {
    const result = applyChange(tasks, unassigned, next, false)
    setTasks(result.tasks)
    setUnassigned(result.unassigned)
    if (next.lunches) setLunches(next.lunches)
    dirtyRef.current = true
    setPendingMoves((current) => [...current, toMoveItem(next.ticketId, next.placement)])
    setChange(null)
    setSelectedTicketId(null)
  }

  /** Вернуть ленту к исходному плану дня — все локальные правки пропадают. */
  const reset = () => {
    dirtyRef.current = false
    setTasks(dataset.tasks)
    setUnassigned(dataset.unassigned)
    setLunches(undefined)
    setPendingMoves([])
    setChange(null)
    setSelectedTicketId(null)
    setManageId(null)
  }

  const shouldBlockLeave = useCallback(() => dirtyRef.current, [])

  /** Отправить накопленные ходы одной новой версией плана. */
  const saveAll = () => {
    if (pendingMoves.length === 0 || saving) return
    if (livePlanId == null) {
      dirtyRef.current = false
      setPendingMoves([])
      toast.success('Изменения сохранены локально')
      return
    }
    const committedKey = key
    const moves = pendingMoves
    setSaving(true)
    moveBatch({ planId: livePlanId, moves, commit: true })
      .unwrap()
      .then((response) => {
        if (response.ok && response.planId != null) {
          // Сначала снимаем dirty: onSaved меняет ?plan= в URL и иначе ловит useBlocker.
          dirtyRef.current = false
          if (keyRef.current === committedKey) {
            setPendingMoves([])
            setLunches(lunchesOf(response))
          }
          toast.success(`План №${response.version} сохранён`, {
            description:
              moves.length === 1
                ? `Заявка №${moves[0].requestId} — ${formatClock(moves[0].start ?? 0)}`
                : `${moves.length} изменений`,
          })
          onSaved?.(response.planId)
          return
        }
        toast.danger('Изменения не сохранены', { description: response.reason })
      })
      .catch(() => {
        toast.danger('Не удалось сохранить изменения', { description: 'План остался без новой версии' })
      })
      .finally(() => setSaving(false))
  }

  /** Проверка постановки: по окнам планировщика, пока их нет / есть черновик — приблизительная. */
  const evaluate = (ticket: GanttTicket, engineer: GanttEngineer, start: number, movingId?: string) => {
    // Окна с backend от исходного плана — после локальных ходов на них нельзя опираться.
    const slots = dirty ? undefined : slotIndex?.get(ticket.id)
    return slots
      ? evaluateBySlots({ ticket, engineer, start, tasks, now, movingId, slots })
      : evaluatePlacement({ ticket, engineer, start, tasks, now, movingId })
  }

  /** Бросили заявку на ленту: сразу ставим или просим подтверждения. `checked` — превью хода. */
  const place = (
    ticketId: string,
    source: GanttChange['source'],
    placement: Placement,
    checked?: PlanMoveResponse | null,
  ) => {
    if (placement.state === 'invalid' || change || saving) return
    const next: GanttChange = { ticketId, source, placement, step: 'swap', lunches: lunchesOf(checked) }
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
    /** Грузится версия плана — в том числе другая, пока на экране прежняя. */
    isLoading: query.isFetching,
    noSchedule,
    /** Есть локальные правки, ещё не сохранённые новой версией. */
    dirty,
    /** Для useBlocker: актуальный dirty без ожидания рендера после «Сохранить». */
    shouldBlockLeave,
    /** Идёт сохранение пакета ходов — новые ходы ждут. */
    saving,
    /** Проверки идут по окнам планировщика, а не приблизительно. */
    exact: !dirty && slotIndex != null,
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
    reset,
    saveAll,
    evaluate,
    /**
     * Можно ли вообще взять заявку: backend отметил неподвижные — старая версия плана,
     * начатая или прошедшая работа. Пока окна не пришли — можно, проверит сам ход.
     */
    canDrag: (ticketId: string) => !readOnly && slotIndex?.get(ticketId)?.movable !== false,
    /** Время, прилипшее к ближайшему окну постановки у инженера. */
    magnet: (ticketId: string, engineerId: string, start: number, raw: number) =>
      dirty ? start : magnetStart(start, raw, slotIndex?.get(ticketId)?.byEngineer.get(engineerId)),
    freeCells: (ticket: GanttTicket, fromHour: number, toHour: number, movingId?: string) => {
      if (dirty) {
        return findFreeCells({ ticket, engineers: dataset.engineers, tasks, now, movingId, fromHour, toHour })
      }
      const slots = slotIndex?.get(ticket.id)
      return slots
        ? findFreeCellsBySlots({ ticket, engineers: dataset.engineers, now, fromHour, toHour, slots })
        : findFreeCells({ ticket, engineers: dataset.engineers, tasks, now, movingId, fromHour, toHour })
    },
    /** Точная проверка хода backend-ом: новое расписание изменившихся маршрутов. */
    preview: (ticketId: string, placement: Placement): Promise<PlanMoveResponse | null> => {
      if (livePlanId == null) return Promise.resolve(null)
      const pending = pendingRef.current
      if (pending.length === 0) {
        return moveRequest(moveArgs(ticketId, placement, false))
          .unwrap()
          .catch(() => null)
      }
      // Уже есть черновик — превью считает цепочку: прежние ходы + текущий, без сохранения.
      return moveBatch({
        planId: livePlanId,
        moves: [...pending, toMoveItem(ticketId, placement)],
        commit: false,
      })
        .unwrap()
        .catch(() => null)
    },
  }
}

export type PlanGanttBoard = ReturnType<typeof usePlanGanttBoard>
