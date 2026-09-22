import { useState, type ReactNode } from 'react'
import { ScrollShadow } from '@heroui/react'
import {
  RiEqualizer2Line,
  RiErrorWarningLine,
  RiSearchLine,
  RiTimeLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

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
    reason: 'Нет инженера на время',
    window: '10:00 - 12:00',
    address: 'Волгоградский пр-т, 128, корп. 5',
  },
  {
    id: '2',
    number: '24980',
    category: 'Авария',
    reason: 'Нет инженера с нужным навыком',
    window: '12:00 - 14:00',
    address: 'Семёновская набережная, д. 3/1, корп. 2',
  },
  {
    id: '3',
    number: '48227',
    category: 'Локальная заявка',
    reason: 'Работа не помещается в смену',
    window: '18:00 - 20:00',
    address: 'ул. Саратовская, 16',
  },
  {
    id: '4',
    number: '86160',
    category: 'Подключение',
    reason: 'Нет свободного инженера',
    window: '18:00 - 20:00',
    address: 'пер. Маяковского, 2',
  },
  {
    id: '5',
    number: '24981',
    category: 'Авария',
    reason: 'Работа не помещается в смену',
    window: '20:00 - 22:00',
    address: 'ул. Артюхиной, 3',
  },
  {
    id: '6',
    number: '30512',
    category: 'Подключение',
    reason: 'Нет инженера на время',
    window: '09:00 - 11:00',
    address: 'ул. Юных Ленинцев, 83, стр. 4',
  },
  {
    id: '7',
    number: '11844',
    category: 'Локальная заявка',
    reason: 'Нет свободного инженера',
    window: '14:00 - 16:00',
    address: 'Рязанский пр-т, 46',
  },
  {
    id: '8',
    number: '67201',
    category: 'Авария',
    reason: 'Нет инженера с нужным навыком',
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

type TicketsPanelProps = {
  className?: string
  tickets?: UnassignedTicket[]
  totalCount?: number
}

export function TicketsPanel({
  className,
  tickets = MOCK_TICKETS,
  totalCount,
}: TicketsPanelProps) {
  const [query, setQuery] = useState('')
  const count = totalCount ?? tickets.length

  const filtered = query.trim()
    ? tickets.filter((ticket) => {
        const q = query.trim().toLowerCase()
        return (
          ticket.number.toLowerCase().includes(q) ||
          ticket.address.toLowerCase().includes(q) ||
          ticket.category.toLowerCase().includes(q)
        )
      })
    : tickets

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

        <button
          type="button"
          className="inline-flex h-9 shrink-0 cursor-pointer items-center gap-2 rounded-[8px] border border-[#dedee0] bg-white px-4 text-sm font-medium leading-5 text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
        >
          <RiEqualizer2Line size={16} className="shrink-0 text-[#18181b]" />
          Фильтры
        </button>
      </div>

      <ScrollShadow
        hideScrollBar
        size={80}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
        <div>
          {filtered.map((ticket) => (
            <TicketCard key={ticket.id} ticket={ticket} />
          ))}
        </div>
      </ScrollShadow>
    </div>
  )
}

export { MOCK_TICKETS }
