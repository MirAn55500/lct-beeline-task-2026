import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { toast } from '@heroui/react'

import { cn } from '@/shared/lib/cn'
import { useAsideWidth } from '@/shared/lib/layout'

import type { GanttTask, GanttTicket, GanttUnassigned } from '../../ganttTypes'
import type { MapTransport } from '../../mapTypes'
import {
  formatClock,
  formatRange,
  isMovable,
  lunchesOf,
  snapMinutes,
  withLunches,
  type Placement,
} from '../../lib/ganttPlacement'
import type { PlanGanttBoard as PlanGanttBoardState } from '../../lib/usePlanGanttBoard'
import type { PlanMoveResponse } from '../../planApi'
import { getClientContact } from '../../mocks/gantt'
import { filterEngineers } from '../EngineerSearchFilters'
import { PlanLoadingBadge } from '../PlanLoadingBadge'
import { GanttTaskCard, GanttTicketCard } from './cards'
import { ClientApprovalDialog } from './ClientApprovalDialog'
import {
  GANTT_HEADER,
  GANTT_HOUR,
  GANTT_ROW,
  GanttTimeline,
  type GanttTarget,
} from './GanttTimeline'
import { GanttUnassignedPanel } from './GanttUnassignedPanel'
import { SwapPopover } from './SwapPopover'
import { TicketManagePanel } from './TicketManagePanel'

// Сдвиг мыши, после которого нажатие считается перетаскиванием, а не кликом.
const DRAG_THRESHOLD = 4
// Пауза в движении, после которой ход проверяет backend: точное расписание и сдвиги соседей.
const PREVIEW_DELAY = 120
// Полоса у края ленты, в которой она сама прокручивается при перетаскивании.
const EDGE = 48
const EDGE_SPEED = 14

type DragState = {
  ticket: GanttTicket
  source: 'unassigned' | 'task'
  x: number
  y: number
  offsetX: number
  offsetY: number
  placement: Placement | null
}

type PlanGanttBoardProps = {
  board: PlanGanttBoardState
  /** Меняется регион или день — лента заново встаёт на текущее время. */
  viewKey: string
}

/** Ключ постановки: превью backend относится ровно к этому месту и времени. */
function placementKey(ticketId: string, placement: Placement) {
  return `${ticketId}:${placement.engineerId}:${placement.start}:${placement.displaced.map((task) => task.id).join(',')}`
}

/** «сдвинутся №12, №13 — до 18:05» — кого подвинет ход по превью backend. */
function shiftText(response: PlanMoveResponse, ticketId: string, tasks: GanttTask[]) {
  const byId = new Map(tasks.map((task) => [task.id, task]))
  const shifted = response.visits.filter((visit) => {
    const task = byId.get(visit.requestId)
    return visit.requestId !== ticketId && task != null && Math.abs(task.start - visit.start) >= 1
  })
  if (shifted.length === 0) return 'без сдвига других заявок'
  const ids = shifted.map((visit) => `№${visit.requestId}`).join(', ')
  const last = Math.max(...shifted.map((visit) => visit.end))
  return `сдвинутся ${ids} — последняя закончится в ${formatClock(last)}`
}

function hintFor(placement: Placement, ticket: GanttTicket, preview: PlanMoveResponse | null, tasks: GanttTask[]) {
  const time = formatRange(placement.start, placement.end)
  if (placement.state === 'invalid') return { tone: 'muted' as const, text: placement.reason ?? 'Сюда нельзя' }
  if (preview && !preview.ok) return { tone: 'danger' as const, text: preview.reason }
  const road = placement.travel ? ` · дорога ${placement.travel} мин` : ''
  const shift = preview ? ` · ${shiftText(preview, ticket.id, tasks)}` : ''
  if (placement.state === 'swap') {
    const ids = placement.displaced.map((task) => `№${task.id}`).join(', ')
    return { tone: 'danger' as const, text: `${time} · заменит ${ids} — потребуется согласование с клиентом${shift}` }
  }
  if (placement.state === 'approval') {
    return {
      tone: 'warning' as const,
      text: `${time}${road} · вне окна клиента ${formatRange(ticket.windowFrom, ticket.windowTo)} — потребуется согласование${shift}`,
    }
  }
  return { tone: 'muted' as const, text: `${time}${road}${shift}` }
}

const HINT_TONE = {
  muted: 'bg-background-inverse text-[var(--beeline-white)]',
  warning: 'bg-[#f59e0b] text-foreground',
  danger: 'bg-danger text-danger-foreground',
}

/** Рабочая область Ганта: лента визитов, неназначенные заявки и подтверждения ручных правок. */
export function PlanGanttBoard({ board, viewKey }: PlanGanttBoardProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const lanesRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [engineerQuery, setEngineerQuery] = useState('')
  const [engineerTransports, setEngineerTransports] = useState<ReadonlySet<MapTransport>>(
    () => new Set(),
  )
  const column = useAsideWidth()
  const { engineers, tasks, now, change } = board
  const visibleEngineers = filterEngineers(engineers, engineerQuery, engineerTransports)
  const visibleEngineerIds = new Set(visibleEngineers.map((engineer) => engineer.id))
  const visibleTasks = tasks.filter((task) => visibleEngineerIds.has(task.engineerId))

  const edges = [
    ...engineers.flatMap((engineer) => engineer.shifts.flat()),
    ...tasks.flatMap((task) => [task.start - task.travel, task.end]),
  ]
  const fromHour = edges.length > 0 ? Math.floor(Math.min(...edges) / 60) : 9
  const toHour = edges.length > 0 ? Math.max(Math.ceil(Math.max(...edges) / 60), fromHour + 1) : 22
  const showNow = board.hasPlan

  const selectedTicket = board.unassigned.find((item) => item.id === board.selectedTicketId) ?? null
  const activeTicket = drag?.ticket ?? selectedTicket
  const movingId = drag?.source === 'task' ? drag.ticket.id : undefined
  const freeCells = activeTicket && !change ? board.freeCells(activeTicket, fromHour, toHour, movingId) : null

  // Точная проверка хода, когда плашку задержали на месте: backend считает новое расписание.
  const [preview, setPreview] = useState<{ key: string; response: PlanMoveResponse | null } | null>(null)
  // Тот же ответ для отпускания плашки: обработчик pointerup живёт дольше рендера.
  const previewRef = useRef(preview)
  const dragKey = drag?.placement && drag.placement.state !== 'invalid' ? placementKey(drag.ticket.id, drag.placement) : null
  useEffect(() => {
    if (!dragKey || !drag?.placement) return
    const { ticket, placement } = drag
    const timer = window.setTimeout(() => {
      void board.preview(ticket.id, placement).then((response) => {
        previewRef.current = { key: dragKey, response }
        setPreview(previewRef.current)
      })
    }, PREVIEW_DELAY)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragKey])
  const currentPreview = preview && preview.key === dragKey ? preview.response : null
  // Заявку держат на времени обеда — обед уже стоит там, куда уедет после хода
  const previewLunches = drag ? lunchesOf(currentPreview) : undefined

  // Как в макете, лента открывается вокруг текущего времени.
  useLayoutEffect(() => {
    const node = scrollRef.current
    if (!node) return
    const nowX = ((now - fromHour * 60) / 60) * GANTT_HOUR
    node.scrollLeft = Math.max(0, nowX - (node.clientWidth - column) / 2)
    node.scrollTop = 0
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey])

  // Esc: сначала отменяет правку, потом снимает выбор, потом закрывает панель заявки.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || change?.step === 'approve') return
      if (change) board.cancelChange()
      else if (board.selectedTicketId) board.selectTicket(null)
      else if (board.manageTicket) board.closeManage()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [board, change])

  /** Что будет, если отпустить заявку в этой точке экрана; null — мимо ленты. */
  const placementAt = (clientX: number, clientY: number, ticket: GanttTicket, grabMinutes: number) => {
    const scroller = scrollRef.current?.getBoundingClientRect()
    const lanes = lanesRef.current?.getBoundingClientRect()
    if (!scroller || !lanes) return null
    if (
      clientX < scroller.left + column ||
      clientX > scroller.right ||
      clientY < scroller.top + GANTT_HEADER ||
      clientY > scroller.bottom
    ) {
      return null
    }
    const engineer = visibleEngineers[Math.floor((clientY - lanes.top) / GANTT_ROW)]
    if (!engineer) return null
    const minute = fromHour * 60 + ((clientX - lanes.left) / GANTT_HOUR) * 60 - grabMinutes
    const start = board.magnet(ticket.id, engineer.id, snapMinutes(minute), minute)
    return board.evaluate(ticket, engineer, start, 'engineerId' in ticket ? ticket.id : undefined)
  }

  const startDrag = (
    ticket: GanttTicket,
    source: DragState['source'],
    event: ReactPointerEvent<HTMLElement>,
    onClick?: () => void,
  ) => {
    if (event.button !== 0 || change) return
    const card = event.currentTarget.getBoundingClientRect()
    const originX = event.clientX
    const originY = event.clientY
    // За визит на ленте держат там, где схватили; неназначенную — за середину.
    const grabMinutes =
      source === 'task' ? ((originX - card.left) / GANTT_HOUR) * 60 : ticket.duration / 2
    const last = { x: originX, y: originY }
    let active = false
    let frame = 0

    const update = () =>
      setDrag({
        ticket,
        source,
        x: last.x,
        y: last.y,
        offsetX: source === 'task' ? originX - card.left : 144,
        offsetY: source === 'task' ? originY - card.top : -12,
        placement: placementAt(last.x, last.y, ticket, grabMinutes),
      })

    // У края ленты прокручиваем её сами, иначе до вечерних часов не дотянуться.
    const autoscroll = () => {
      const node = scrollRef.current
      if (node) {
        const rect = node.getBoundingClientRect()
        const insideY = last.y > rect.top && last.y < rect.bottom
        const insideX = last.x > rect.left + column && last.x < rect.right
        let dx = 0
        let dy = 0
        if (insideY && last.x > rect.right - EDGE && last.x < rect.right) dx = EDGE_SPEED
        if (insideY && last.x > rect.left + column && last.x < rect.left + column + EDGE) dx = -EDGE_SPEED
        if (insideX && last.y > rect.bottom - EDGE && last.y < rect.bottom) dy = EDGE_SPEED
        if (insideX && last.y > rect.top + GANTT_HEADER && last.y < rect.top + GANTT_HEADER + EDGE) dy = -EDGE_SPEED
        if (dx !== 0 || dy !== 0) {
          node.scrollBy(dx, dy)
          update()
        }
      }
      frame = requestAnimationFrame(autoscroll)
    }

    const move = (next: PointerEvent) => {
      last.x = next.clientX
      last.y = next.clientY
      if (!active && Math.hypot(last.x - originX, last.y - originY) < DRAG_THRESHOLD) return
      if (!active) {
        active = true
        document.body.style.userSelect = 'none'
        frame = requestAnimationFrame(autoscroll)
      }
      update()
    }
    const finish = (cancelled: boolean) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      cancelAnimationFrame(frame)
      document.body.style.userSelect = ''
      setDrag(null)
      if (cancelled) return
      if (!active) {
        onClick?.()
        return
      }
      const placement = placementAt(last.x, last.y, ticket, grabMinutes)
      if (!placement) return
      // Backend уже проверил это место и отказал — не ставим, говорим почему.
      const checked = previewRef.current
      if (placement.state !== 'invalid' && checked?.key === placementKey(ticket.id, placement) && checked.response?.ok === false) {
        toast.danger('Сюда не встанет', { description: checked.response.reason })
        return
      }
      // Дорога — из точного превью, если оно успело: у замены окна планировщика нет.
      const visit =
        checked?.key === placementKey(ticket.id, placement)
          ? checked.response?.visits.find((item) => item.requestId === ticket.id)
          : undefined
      board.place(
        ticket.id,
        source,
        visit ? { ...placement, travel: Math.round(visit.travelMinutes) } : placement,
        checked?.key === placementKey(ticket.id, placement) ? checked.response : null,
      )
    }
    const onUp = () => finish(false)
    const onCancel = () => finish(true)

    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onCancel)
  }

  const target: GanttTarget | null = drag?.placement
    ? {
        engineerId: drag.placement.engineerId,
        from: Math.max(fromHour * 60, drag.placement.start),
        to: Math.min(toHour * 60, drag.placement.end),
        snapStart: drag.placement.start,
        tone: drag.placement.state === 'ok' || drag.placement.state === 'approval' ? 'target' : 'danger',
      }
    : null
  const hint = drag?.placement ? hintFor(drag.placement, drag.ticket, currentPreview, tasks) : null

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="relative flex min-w-0 flex-1 flex-col gap-4">
        <PlanLoadingBadge active={board.isLoading} />
        <GanttTimeline
          column={column}
          engineers={previewLunches ? withLunches(visibleEngineers, previewLunches) : visibleEngineers}
          tasks={visibleTasks}
          engineerQuery={engineerQuery}
          onEngineerQueryChange={setEngineerQuery}
          engineerTransports={engineerTransports}
          onEngineerTransportsChange={setEngineerTransports}
          fromHour={fromHour}
          toHour={toHour}
          now={showNow ? now : null}
          freeCells={freeCells}
          target={target}
          dragging={drag != null}
          draggingTaskId={movingId ?? null}
          scrollRef={scrollRef}
          lanesRef={lanesRef}
          onTaskPointerDown={(task: GanttTask, event) => {
            if (isMovable(task) && board.canDrag(task.id)) startDrag(task, 'task', event)
          }}
          canDrag={(task: GanttTask) => isMovable(task) && board.canDrag(task.id)}
          onFreeCellClick={(engineerId, start) => {
            const engineer = engineers.find((item) => item.id === engineerId)
            if (!selectedTicket || !engineer) return
            board.place(selectedTicket.id, 'unassigned', board.evaluate(selectedTicket, engineer, start))
          }}
          onBackgroundClick={() => {
            if (board.selectedTicketId) board.selectTicket(null)
          }}
        />

        <GanttUnassignedPanel
          tickets={board.unassigned}
          empty={!board.hasPlan}
          emptyText={
            board.noSchedule
              ? 'В этой версии плана нет расписания визитов — она составлена до его появления. Обновите план'
              : undefined
          }
          selectedId={board.selectedTicketId}
          draggingId={drag?.source === 'unassigned' ? drag.ticket.id : null}
          canDrag={(ticket: GanttUnassigned) => board.canDrag(ticket.id)}
          onDragStart={(ticket: GanttUnassigned, event) =>
            startDrag(ticket, 'unassigned', event, () => board.selectTicket(ticket.id))
          }
          onApprove={board.openManage}
        />
      </div>

      {board.manageTicket ? (
        <TicketManagePanel
          key={board.manageTicket.id}
          ticket={board.manageTicket}
          ticketTypes={board.ticketTypes}
          qualifications={board.qualifications}
          onSave={(patch) => board.saveTicket(board.manageTicket!.id, patch)}
          onClose={board.closeManage}
        />
      ) : null}

      {drag
        ? createPortal(
            <div
              className="pointer-events-none fixed z-50 flex flex-col items-center gap-1"
              style={{ left: drag.x - drag.offsetX, top: drag.y - drag.offsetY }}
            >
              {drag.source === 'task' && 'engineerId' in drag.ticket ? (
                <GanttTaskCard task={drag.ticket as GanttTask} full className="w-[204px] opacity-80" />
              ) : (
                <>
                  <svg width={12} height={8} viewBox="0 0 12 8" aria-hidden className="-mb-1 text-[#475569]">
                    <path d="M6 0 12 8H0z" fill="currentColor" />
                  </svg>
                  <GanttTicketCard
                    ticket={drag.ticket as GanttUnassigned}
                    selected
                    className="shadow-[0_20px_25px_-5px_rgb(0_0_0/0.1),0_8px_10px_-6px_rgb(0_0_0/0.1)]"
                  />
                </>
              )}
              {hint ? (
                <span
                  className={cn('max-w-[288px] px-2 py-1 text-xs leading-4 font-medium', HINT_TONE[hint.tone])}
                  style={{ borderRadius: 6 }}
                >
                  {hint.text}
                </span>
              ) : null}
            </div>,
            document.body,
          )
        : null}

      {change?.step === 'swap' ? (
        <SwapPopover
          anchorTaskId={change.ticketId}
          displaced={change.placement.displaced}
          scrollRef={scrollRef}
          onConfirm={board.confirmSwap}
          onCancel={board.cancelChange}
        />
      ) : null}

      <ClientApprovalDialog
        open={change?.step === 'approve'}
        contact={change ? getClientContact(change.ticketId) : null}
        timeLabel={change ? formatRange(change.placement.start, change.placement.end) : ''}
        onConfirm={board.confirmApproval}
        onCancel={board.cancelChange}
      />
    </div>
  )
}
