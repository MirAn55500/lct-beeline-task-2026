import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'

import { cn } from '@/shared/lib/cn'

import type { PlanMapBoard as PlanMapBoardState } from '../../lib/usePlanMapBoard'
import type { UnassignedTicket } from '../../mapTypes'
import { PlanMap } from '../PlanMap'
import { ReplanDialog } from './ReplanDialog'
import { RouteParamsDialog } from './RouteParamsDialog'
import { ROUTE_PANEL_INSET, RouteDetailsPanel } from './RouteDetailsPanel'
import { TicketCard, UnassignedTicketsPanel } from './UnassignedTicketsPanel'

// Сдвиг мыши, после которого нажатие на карточку считается перетаскиванием.
const DRAG_THRESHOLD = 4
// Сколько держится подсветка ленты после «Добавить заявку».
const HINT_MS = 1600

type DragState = {
  ticket: UnassignedTicket
  x: number
  y: number
  offsetX: number
  offsetY: number
  width: number
  index: number | null
}

type PlanMapBoardProps = {
  board: PlanMapBoardState
  onCancelStop?: (requestId: string) => void
  /** Старая версия или прошедший день: заявки в маршрут не добавляются. */
  readOnly?: boolean
}

/** Рабочая область карты: маршруты, панель выбранного маршрута и неназначенные заявки. */
export function PlanMapBoard({ board, onCancelStop, readOnly = false }: PlanMapBoardProps) {
  const listRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [hint, setHint] = useState(false)
  const [paramsOpen, setParamsOpen] = useState(false)
  const { selectedEngineer, selectedRoute, pendingDrop } = board

  useEffect(() => {
    if (!hint) return
    const timer = setTimeout(() => setHint(false), HINT_MS)
    return () => clearTimeout(timer)
  }, [hint])

  // Esc снимает выбор инженера, если не открыто окно подтверждения.
  useEffect(() => {
    if (!selectedEngineer || pendingDrop || paramsOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') board.select(null)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [board, selectedEngineer, pendingDrop, paramsOpen])

  /** Куда встанет заявка: индекс среди заявок маршрута или null, если курсор вне списка. */
  const hitIndex = (x: number, y: number) => {
    const list = listRef.current
    if (!list) return null
    const rect = list.getBoundingClientRect()
    if (x < rect.left || x > rect.right + 24 || y < rect.top || y > rect.bottom) return null
    const items = list.querySelectorAll<HTMLElement>('[data-stop-index]')
    for (const [index, item] of items.entries()) {
      const box = item.getBoundingClientRect()
      if (y < box.top + box.height / 2) return index
    }
    return items.length
  }

  const startDrag = (ticket: UnassignedTicket, event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0 || !selectedEngineer) return
    const card = event.currentTarget.getBoundingClientRect()
    const originX = event.clientX
    const originY = event.clientY
    const engineerId = selectedEngineer.id
    let active = false

    const move = (next: PointerEvent) => {
      if (!active && Math.hypot(next.clientX - originX, next.clientY - originY) < DRAG_THRESHOLD) return
      active = true
      document.body.style.userSelect = 'none'
      setDrag({
        ticket,
        x: next.clientX,
        y: next.clientY,
        offsetX: originX - card.left,
        offsetY: originY - card.top,
        width: card.width,
        index: hitIndex(next.clientX, next.clientY),
      })
    }
    const finish = (last: PointerEvent, cancelled: boolean) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      document.body.style.userSelect = ''
      setDrag(null)
      if (!active || cancelled) return
      const index = hitIndex(last.clientX, last.clientY)
      if (index != null) board.requestDrop({ ticket, engineerId, index })
    }
    const onUp = (last: PointerEvent) => finish(last, false)
    const onCancel = (last: PointerEvent) => finish(last, true)

    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onCancel)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <PlanMap
        engineers={board.engineers}
        routes={board.routes}
        selectedId={board.selectedId}
        hoveredId={board.hoveredId}
        activeStopId={board.activeStopId}
        overlayInset={selectedEngineer ? ROUTE_PANEL_INSET : 0}
        viewKey={board.viewKey}
        onHoverEngineer={board.hover}
        onSelectEngineer={board.select}
        onSelectStop={board.toggleStop}
      >
        {selectedEngineer && selectedRoute ? (
          <RouteDetailsPanel
            engineer={selectedEngineer}
            route={selectedRoute}
            activeStopId={board.activeStopId}
            onToggleStop={board.toggleStop}
            onAddTicket={readOnly ? undefined : () => setHint(true)}
            onEditParams={() => setParamsOpen(true)}
            onCancelStop={onCancelStop}
            dropIndex={drag?.index ?? null}
            listRef={listRef}
          />
        ) : null}
      </PlanMap>

      {selectedEngineer ? (
        <div
          className={cn(
            'rounded-[var(--border-radius-panel)] ring-2 ring-transparent transition-shadow duration-300',
            hint && 'ring-focus',
          )}
        >
          <UnassignedTicketsPanel
            tickets={board.unassigned}
            draggingId={drag?.ticket.id ?? null}
            onDragStart={startDrag}
          />
        </div>
      ) : null}

      {drag
        ? createPortal(
            <div
              className="pointer-events-none fixed z-50"
              style={{ left: drag.x - drag.offsetX, top: drag.y - drag.offsetY, width: drag.width }}
            >
              <TicketCard ticket={drag.ticket} floating />
            </div>,
            document.body,
          )
        : null}

      {paramsOpen && selectedEngineer && selectedRoute ? (
        <RouteParamsDialog
          isOpen
          engineer={selectedEngineer}
          route={selectedRoute}
          onClose={() => setParamsOpen(false)}
          onApply={(variant) => board.applyVariant(selectedEngineer.id, variant)}
        />
      ) : null}

      <ReplanDialog
        ticketId={pendingDrop?.ticket.id ?? null}
        engineerName={board.engineers.find((item) => item.id === pendingDrop?.engineerId)?.name}
        onConfirm={board.confirmDrop}
        onCancel={board.cancelDrop}
      />
    </div>
  )
}
