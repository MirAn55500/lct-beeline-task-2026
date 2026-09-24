import { useState } from 'react'

import type { GanttEngineer, GanttTask, GanttTicket, GanttUnassigned } from '../ganttTypes'
import { MOCK_GANTT_NOW, getGanttDataset } from '../mocks/gantt'
import { formatRange, type Placement } from './ganttPlacement'

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

/**
 * Состояние страницы Ганта на моках. На другой день без плана лента пустая, как «Ganta — Empty».
 * Когда появится API, визиты придут из RTK Query, а ручные постановки уйдут мутацией перепланирования.
 */
export function usePlanGanttBoard(regionId: number | null, date: string) {
  const dataset = getGanttDataset(regionId)
  const hasPlan = date === dataset.date
  const key = `${regionId}:${date}`

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
    date: dataset.date,
    hasPlan,
    now: MOCK_GANTT_NOW,
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
