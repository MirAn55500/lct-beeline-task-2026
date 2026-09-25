import { useRef, useState, type PointerEvent } from 'react'
import { RiDraggable } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { pluralRu } from '@/shared/lib'
import { AppPanel } from '@/shared/ui'

import type { UnassignedTicket } from '../../mapTypes'
import { UNASSIGNED_REASON_LABEL } from '../../mocks'
import { sortTickets, type TicketSortKey } from '../../lib/ticketSort'
import { PagingArrows, TicketSortMenu } from '../TicketListControls'
import { ReasonTag, TicketTags } from './parts'

// Окно «9:00–11:00» сравниваем по минутам начала, чтобы 9:00 шло раньше 10:00.
const windowStart = (ticket: UnassignedTicket) => {
  const [hours = '0', minutes = '0'] = ticket.window.split('–')[0]!.split(':')
  return Number(hours) * 60 + Number(minutes)
}

type UnassignedTicketsPanelProps = {
  tickets: UnassignedTicket[]
  /** Карточка, которую сейчас тащат, — на её месте остаётся пунктирная заглушка. */
  draggingId: string | null
  onDragStart: (ticket: UnassignedTicket, event: PointerEvent<HTMLElement>) => void
}

export function UnassignedTicketsPanel({
  tickets,
  draggingId,
  onDragStart,
}: UnassignedTicketsPanelProps) {
  const [sort, setSort] = useState<TicketSortKey>('window')
  const scrollRef = useRef<HTMLDivElement>(null)
  const sorted = sortTickets(tickets, sort, windowStart)

  return (
    <AppPanel className="flex h-[226px] shrink-0 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-4 px-5 py-4">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <h2 className="truncate py-0.5 text-xl leading-7 font-semibold text-foreground">
            {tickets.length}{' '}
            {pluralRu(tickets.length, [
              'неназначенная заявка',
              'неназначенные заявки',
              'неназначенных заявок',
            ])}
          </h2>
          <TicketSortMenu value={sort} onChange={setSort} />
        </div>

        <PagingArrows scrollRef={scrollRef} itemCount={tickets.length} className="gap-2" />
      </div>

      {tickets.length === 0 ? (
        <p className="flex flex-1 items-center justify-center px-5 pb-5 text-sm leading-5 text-muted">
          Все заявки распределены
        </p>
      ) : (
        <div
          ref={scrollRef}
          className="flex min-h-0 flex-1 snap-x snap-mandatory scroll-px-5 gap-1.5 overflow-x-auto px-5 pb-5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {sorted.map((ticket) =>
            ticket.id === draggingId ? (
              <div
                key={ticket.id}
                aria-hidden
                className="h-[142px] w-[calc((100%-18px)/4)] min-w-[220px] shrink-0 snap-start border border-dashed border-border bg-surface-tertiary"
                style={{ borderRadius: 8 }}
              />
            ) : (
              <TicketCard
                key={ticket.id}
                ticket={ticket}
                className="w-[calc((100%-18px)/4)] min-w-[220px] shrink-0 snap-start"
                onPointerDown={(event) => onDragStart(ticket, event)}
              />
            ),
          )}
        </div>
      )}
    </AppPanel>
  )
}

export function TicketCard({
  ticket,
  className,
  floating = false,
  onPointerDown,
}: {
  ticket: UnassignedTicket
  className?: string
  /** Карточка в руке при перетаскивании — с тенью, без рамки. */
  floating?: boolean
  onPointerDown?: (event: PointerEvent<HTMLElement>) => void
}) {
  return (
    <article
      onPointerDown={onPointerDown}
      className={cn(
        'relative flex h-[142px] touch-none flex-col gap-2 bg-surface p-3 select-none',
        floating
          ? 'shadow-[0_20px_25px_-5px_rgb(0_0_0/0.1),0_8px_10px_-6px_rgb(0_0_0/0.1)]'
          : 'cursor-grab border border-border active:cursor-grabbing',
        className,
      )}
      style={{ borderRadius: 8 }}
    >
      <div className="flex min-w-0 flex-col gap-1 pr-5">
        <p className="flex items-center gap-1 truncate text-sm leading-5 font-medium">
          <span className="text-foreground">№{ticket.id}</span>
          <span className="text-muted">•</span>
          <span className="truncate text-muted">{ticket.typeLabel}</span>
        </p>
        <p className="line-clamp-2 h-10 text-sm leading-5 text-foreground">{ticket.address}</p>
      </div>
      <div className="flex min-w-0 flex-col items-start gap-1.5">
        <ReasonTag label={UNASSIGNED_REASON_LABEL[ticket.reason]} explanation={ticket.explanation} />
        <TicketTags ticket={ticket} />
      </div>
      <RiDraggable
        size={16}
        aria-hidden
        className="absolute top-1/2 right-1.5 -translate-y-1/2 text-muted"
      />
    </article>
  )
}
