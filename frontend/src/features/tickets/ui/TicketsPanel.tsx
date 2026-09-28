import { useEffect, useState, type ReactNode } from 'react'
import { ScrollShadow, Tooltip } from '@heroui/react'
import {
  RiErrorWarningLine,
  RiSearchLine,
  RiTimeLine,
  RiUserLine,
} from '@remixicon/react'

import { useGetTicketsQuery, type Ticket } from '@/features/tickets/api'
import { cn } from '@/shared/lib/cn'
import { AppTooltipContent } from '@/shared/ui'
import {
  EMPTY_TICKETS_FILTERS,
  TicketsFiltersPopover,
  type TicketsFiltersState,
} from './TicketsFiltersPopover'

export type { Ticket }

function TicketTag({
  tone,
  icon,
  children,
  hint,
}: {
  tone: 'danger' | 'neutral'
  icon: ReactNode
  children: ReactNode
  hint?: string | null
}) {
  const tag = (
    <span
      className="inline-flex h-6 max-w-full items-center gap-1 px-1.5 py-1 text-xs font-medium leading-5"
      style={{
        borderRadius: 4,
        backgroundColor: tone === 'danger' ? 'var(--danger-soft)' : 'var(--surface-tertiary)',
        color: tone === 'danger' ? 'var(--danger-soft-foreground)' : 'var(--foreground)',
      }}
    >
      <span className="inline-flex size-3 shrink-0 items-center justify-center">
        {icon}
      </span>
      <span className="truncate">{children}</span>
    </span>
  )

  if (!hint) return tag

  return (
    <Tooltip delay={200}>
      <Tooltip.Trigger className="inline-flex max-w-full cursor-help outline-none">
        {tag}
      </Tooltip.Trigger>
      <AppTooltipContent className="max-w-[280px] text-left break-normal">
        {hint}
      </AppTooltipContent>
    </Tooltip>
  )
}

/** Пояснение к причине неназначения — в подсказке на теге, как в макете. */
function reasonHint(reason: string) {
  const text = reason.toLowerCase()
  if (text.includes('навык')) return 'У инженеров региона нет навыка для этого вида работ'
  if (text.includes('снаряж') || text.includes('оборудован')) return 'У подходящих инженеров нет нужного оборудования'
  if (text.includes('смен') || text.includes('рабочего времени')) return 'Работа не помещается в рабочие смены инженеров'
  if (text.includes('конфликт') || text.includes('график')) return 'Окно клиента пересекается с другими визитами инженеров'
  return 'Инженеры региона отсутствуют или недоступны на нужное время'
}

function TicketCard({ ticket }: { ticket: Ticket }) {
  return (
    <article className="flex flex-col gap-2 border-b border-border px-5 py-3">
      <div className="flex min-w-0 items-center gap-1.5 text-base font-semibold leading-6">
        <span className="shrink-0 text-foreground">№{ticket.number}</span>
        <span className="shrink-0 text-muted">•</span>
        <span className="truncate text-muted">{ticket.category}</span>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {ticket.assigned && ticket.engineer ? (
          <TicketTag
            tone="neutral"
            icon={<RiUserLine size={12} className="text-muted" />}
          >
            {ticket.engineer}
          </TicketTag>
        ) : ticket.reason ? (
          <TicketTag
            tone="danger"
            icon={<RiErrorWarningLine size={12} className="text-danger-soft-foreground" />}
            hint={ticket.reason_hint ?? reasonHint(ticket.reason)}
          >
            {ticket.reason}
          </TicketTag>
        ) : null}
        <TicketTag
          tone="neutral"
          icon={<RiTimeLine size={12} className="text-muted" />}
        >
          {ticket.window}
        </TicketTag>
      </div>

      <p className="truncate text-sm leading-6 text-muted">{ticket.address}</p>
    </article>
  )
}

type TicketsPanelProps = {
  className?: string
  regionId: number
  date: string
  planId?: number | null
}

export function TicketsPanel({
  className,
  regionId,
  date,
  planId = null,
}: TicketsPanelProps) {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [filters, setFilters] = useState<TicketsFiltersState>(EMPTY_TICKETS_FILTERS)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 300)
    return () => window.clearTimeout(timer)
  }, [query])

  const { data: tickets = [], isFetching, isError } = useGetTicketsQuery({
    regionId,
    date,
    planId,
    assignment: filters.assignment,
    q: debouncedQuery.trim() || undefined,
    workTypes: filters.workTypes,
    reasons: filters.reasons,
    timeFrom: filters.timeFrom,
    timeTo: filters.timeTo,
  })

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
      <div className="flex shrink-0 flex-col px-5 pb-3 pt-5">
        <h2 className="text-xl font-semibold leading-7 text-foreground">
          Загруженные заявки
        </h2>
      </div>

      <div className="flex shrink-0 items-center gap-3 px-5 pb-3">
        <label className="relative flex h-9 min-w-0 flex-1 items-center rounded-[8px] border border-border bg-surface px-3">
          <RiSearchLine
            size={16}
            className="pointer-events-none shrink-0 text-muted"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск по адресу или номеру заявки"
            className="min-w-0 flex-1 border-0 bg-transparent py-2 ps-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted"
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
          {isError ? (
            <p className="px-5 py-8 text-center text-sm text-muted">
              Не удалось загрузить заявки
            </p>
          ) : tickets.length > 0 ? (
            tickets.map((ticket) => <TicketCard key={ticket.id} ticket={ticket} />)
          ) : (
            <p className="px-5 py-8 text-center text-sm text-muted">
              {isFetching ? 'Загрузка заявок' : 'Нет заявок по выбранным фильтрам'}
            </p>
          )}
        </div>
      </ScrollShadow>
    </div>
  )
}
