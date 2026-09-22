import { useMemo, useState, type ReactNode } from 'react'
import { ScrollShadow } from '@heroui/react'
import {
  RiErrorWarningLine,
  RiSearchLine,
  RiTimeLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import {
  EMPTY_TICKETS_FILTERS,
  ticketMatchesTimeWindow,
  TicketsFiltersPopover,
  type TicketsFiltersState,
} from './TicketsFiltersPopover'

export type UnassignedTicket = {
  id: string
  number: string
  category: string
  reason: string
  window: string
  address: string
}

const MOCK_TICKETS: UnassignedTicket[] = [
  {
    id: '1',
    number: '74198',
    category: 'Подключение',
    reason: 'Нет рабочего времени',
    window: '10:00 - 12:00',
    address: 'Волгоградский пр-т, 128, корп. 5',
  },
  {
    id: '2',
    number: '24980',
    category: 'Аварийные работы',
    reason: 'Нет нужного навыка',
    window: '12:00 - 14:00',
    address: 'Семёновская набережная, д. 3/1, корп. 2',
  },
  {
    id: '3',
    number: '48227',
    category: 'Ремонт',
    reason: 'Конфликт времени',
    window: '18:00 - 20:00',
    address: 'ул. Саратовская, 16',
  },
  {
    id: '4',
    number: '86160',
    category: 'Подключение',
    reason: 'Нет инженера в регионе',
    window: '18:00 - 20:00',
    address: 'пер. Маяковского, 2',
  },
  {
    id: '5',
    number: '24981',
    category: 'Аварийные работы',
    reason: 'Конфликт времени',
    window: '20:00 - 22:00',
    address: 'ул. Артюхиной, 3',
  },
  {
    id: '6',
    number: '30512',
    category: 'Дозаказ',
    reason: 'Нет рабочего времени',
    window: '09:00 - 11:00',
    address: 'ул. Юных Ленинцев, 83, стр. 4',
  },
  {
    id: '7',
    number: '11844',
    category: 'Ремонт',
    reason: 'Нет нужного снаряжения',
    window: '14:00 - 16:00',
    address: 'Рязанский пр-т, 46',
  },
  {
    id: '8',
    number: '67201',
    category: 'Аварийные работы',
    reason: 'Нет нужного навыка',
    window: '16:00 - 18:00',
    address: 'ул. Авиамоторная, 12',
  },
]

function formatUnassignedTitle(count: number) {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) {
    return `${count} неназначенная заявка`
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} неназначенные заявки`
  }
  return `${count} неназначенных заявок`
}

function TicketTag({
  tone,
  icon,
  children,
}: {
  tone: 'danger' | 'neutral'
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <span
      className="inline-flex h-6 max-w-full items-center gap-1 px-1.5 py-1 text-xs font-medium leading-5"
      style={{
        borderRadius: 4,
        backgroundColor: tone === 'danger' ? 'rgba(255, 56, 60, 0.15)' : '#ebebec',
        color: tone === 'danger' ? '#a43532' : '#18181b',
      }}
    >
      <span className="inline-flex size-3 shrink-0 items-center justify-center">
        {icon}
      </span>
      <span className="truncate">{children}</span>
    </span>
  )
}

function TicketCard({ ticket }: { ticket: UnassignedTicket }) {
  return (
    <article className="flex flex-col gap-2 border-b border-[#dedee0] px-5 py-3">
      <div className="flex min-w-0 items-center gap-1.5 text-base font-semibold leading-6">
        <span className="shrink-0 text-[#18181b]">№{ticket.number}</span>
        <span className="shrink-0 text-[#71717a]">•</span>
        <span className="truncate text-[#71717a]">{ticket.category}</span>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <TicketTag
          tone="danger"
          icon={<RiErrorWarningLine size={12} className="text-[#a43532]" />}
        >
          {ticket.reason}
        </TicketTag>
        <TicketTag
          tone="neutral"
          icon={<RiTimeLine size={12} className="text-[#71717a]" />}
        >
          {ticket.window}
        </TicketTag>
      </div>

      <p className="truncate text-sm leading-6 text-[#71717a]">{ticket.address}</p>
    </article>
  )
}

function applyTicketFilters(
  tickets: UnassignedTicket[],
  query: string,
  filters: TicketsFiltersState,
) {
  const q = query.trim().toLowerCase()

  return tickets.filter((ticket) => {
    if (q) {
      const matchesQuery =
        ticket.number.toLowerCase().includes(q) ||
        ticket.address.toLowerCase().includes(q) ||
        ticket.category.toLowerCase().includes(q) ||
        ticket.reason.toLowerCase().includes(q)
      if (!matchesQuery) return false
    }

    if (
      filters.workTypes.length > 0 &&
      !filters.workTypes.includes(ticket.category)
    ) {
      return false
    }

    if (
      filters.reasons.length > 0 &&
      !filters.reasons.includes(ticket.reason)
    ) {
      return false
    }

    return ticketMatchesTimeWindow(
      ticket.window,
      filters.timeFrom,
      filters.timeTo,
    )
  })
}

type TicketsPanelProps = {
  className?: string
  tickets?: UnassignedTicket[]
}

export function TicketsPanel({
  className,
  tickets = MOCK_TICKETS,
}: TicketsPanelProps) {
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<TicketsFiltersState>(
    EMPTY_TICKETS_FILTERS,
  )

  const filtered = useMemo(
    () => applyTicketFilters(tickets, query, filters),
    [tickets, query, filters],
  )

  const count = filtered.length

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
      <div className="flex shrink-0 flex-col gap-1 px-5 pb-5 pt-5">
        <h2 className="text-xl font-semibold leading-7 text-[#18181b]">
          {formatUnassignedTitle(count)}
        </h2>
        <p className="text-sm leading-6 text-[#71717a]">
          Загрузите заявки для начала работы алгоритма
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-3 px-5 pb-3">
        <label className="relative flex h-9 min-w-0 flex-1 items-center rounded-[8px] border border-[#dedee0] bg-white px-3">
          <RiSearchLine
            size={16}
            className="pointer-events-none shrink-0 text-[#71717a]"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск по адресу или номеру заявки"
            className="min-w-0 flex-1 border-0 bg-transparent py-2 ps-2 text-sm leading-5 text-[#18181b] outline-none placeholder:text-[#71717a]"
          />
        </label>

        <TicketsFiltersPopover value={filters} onChange={setFilters} />
      </div>

      <ScrollShadow
        hideScrollBar
        size={80}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
        <div>
          {filtered.length > 0 ? (
            filtered.map((ticket) => (
              <TicketCard key={ticket.id} ticket={ticket} />
            ))
          ) : (
            <p className="px-5 py-8 text-center text-sm text-[#71717a]">
              Нет заявок по выбранным фильтрам
            </p>
          )}
        </div>
      </ScrollShadow>
    </div>
  )
}

export { MOCK_TICKETS }
