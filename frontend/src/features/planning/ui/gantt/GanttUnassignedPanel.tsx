import { useRef, useState, type PointerEvent } from 'react'

import { AppPanel } from '@/shared/ui'

import type { GanttUnassigned } from '../../ganttTypes'
import { sortTickets, type TicketSortKey } from '../../lib/ticketSort'
import { PagingArrows, TicketSortMenu } from '../TicketListControls'
import { GanttTicketCard } from './cards'

type GanttUnassignedPanelProps = {
  tickets: GanttUnassigned[]
  /** Нет плана на день — панель пустая, без счётчика. */
  empty: boolean
  selectedId: string | null
  draggingId: string | null
  onDragStart: (ticket: GanttUnassigned, event: PointerEvent<HTMLElement>) => void
  onApprove: (ticketId: string) => void
}

export function GanttUnassignedPanel({
  tickets,
  empty,
  selectedId,
  draggingId,
  onDragStart,
  onApprove,
}: GanttUnassignedPanelProps) {
  const [sort, setSort] = useState<TicketSortKey>('window')
  const scrollRef = useRef<HTMLDivElement>(null)
  // Снятые при замене ждут согласования — держим их первыми, чтобы не потерялись.
  const sorted = sortTickets(tickets, sort, (ticket) => ticket.windowFrom).sort(
    (a, b) => Number(b.needsApproval === true) - Number(a.needsApproval === true),
  )

  return (
    <AppPanel className="flex h-[164px] shrink-0 flex-col gap-3 overflow-hidden p-3">
      <div className="flex h-8 shrink-0 items-center gap-2">
        <h2 className="truncate text-xl leading-7 font-semibold text-[#18181b]">
          Неназначенные заявки{empty ? '' : ` · ${tickets.length}`}
        </h2>
        <TicketSortMenu value={sort} onChange={setSort} />
        <PagingArrows scrollRef={scrollRef} itemCount={tickets.length} className="ml-auto" />
      </div>

      {empty ? null : tickets.length === 0 ? (
        <p className="flex flex-1 items-center justify-center text-sm leading-5 text-[#71717a]">
          Все заявки распределены
        </p>
      ) : (
        <div
          ref={scrollRef}
          className="-mx-3 flex min-h-0 flex-1 snap-x snap-mandatory scroll-px-3 gap-2 overflow-x-auto px-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {sorted.map((ticket) =>
            ticket.id === draggingId ? (
              <div
                key={ticket.id}
                aria-hidden
                className="h-24 w-[288px] shrink-0 snap-start border border-dashed border-[#dedee0] bg-[#efeff0]"
                style={{ borderRadius: 8 }}
              />
            ) : (
              <GanttTicketCard
                key={ticket.id}
                ticket={ticket}
                selected={ticket.id === selectedId}
                className="snap-start"
                onPointerDown={(event) => onDragStart(ticket, event)}
                onApprove={() => onApprove(ticket.id)}
              />
            ),
          )}
        </div>
      )}
    </AppPanel>
  )
}
