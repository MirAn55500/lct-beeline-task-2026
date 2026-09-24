import { Link } from 'react-router'

import beesPromo from '@/shared/assets/day-overview-bees-promo.png'
import { EngineersPanel } from '@/features/personnel'
import { TicketsDropzone, TicketsPanel } from '@/features/tickets'
import { useGetTicketsQuery, type Ticket } from '@/features/tickets/api'
import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import { useGetDayOverviewQuery } from '../api'
import { DayPlanPreview, type PlanRow } from './DayPlanPreview'

function PanelHeading({
  title,
  description,
  className,
}: {
  title: string
  description: string
  className?: string
}) {
  return (
    <div className={cn('flex shrink-0 flex-col gap-1 px-5 pt-5', className)}>
      <h2 className="text-xl font-semibold leading-7 text-foreground">{title}</h2>
      <p className="text-sm leading-6 text-[#71717a]">{description}</p>
    </div>
  )
}

function SummaryCounter({
  value,
  total,
  label,
}: {
  value: number
  total: number
  label: string
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <div className="flex items-baseline gap-1 text-xl font-semibold leading-7">
        <span className="text-foreground">{value}</span>
        <span className="text-[#71717a]">из {total}</span>
      </div>
      <p className="text-sm leading-6 text-[#71717a]">{label}</p>
    </div>
  )
}

function planRowsFromTickets(tickets: Ticket[]): PlanRow[] {
  const grouped = new Map<string, PlanRow['blocks']>()
  for (const ticket of tickets) {
    if (!ticket.assigned || !ticket.engineer) continue
    const match = /^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$/.exec(ticket.window.trim())
    if (!match) continue
    const from = Number(match[1]) + Number(match[2]) / 60
    const to = Number(match[3]) + Number(match[4]) / 60
    if (!(to > from)) continue
    const blocks = grouped.get(ticket.engineer) ?? []
    blocks.push({
      from,
      to,
      tone: ticket.category.toLowerCase().includes('авар') ? 'strong' : 'soft',
    })
    grouped.set(ticket.engineer, blocks)
  }
  return [...grouped.entries()].map(([name, blocks]) => ({ id: name, name, blocks }))
}

type DayOverviewWorkspaceProps = {
  className?: string
  regionId?: number | null
  regionName?: string | null
  date?: string
  planId?: number | null
  isUploading?: boolean
  onFiles?: (files: File[]) => void | Promise<void>
}

export function DayOverviewWorkspace({
  className,
  regionId = null,
  regionName = null,
  date = '',
  planId = null,
  isUploading = false,
  onFiles,
}: DayOverviewWorkspaceProps) {
  const { data: overview, isFetching: overviewLoading } = useGetDayOverviewQuery(
    { regionId: regionId ?? 0, date, planId },
    { skip: regionId == null || date === '' },
  )
  const hasTickets = (overview?.tickets.total ?? 0) > 0
  const { data: chartTickets = [] } = useGetTicketsQuery(
    { regionId: regionId ?? 0, date, planId },
    { skip: !hasTickets || regionId == null },
  )
  const regionLabel = regionName ?? '—'
  const showUploader = !hasTickets && !(overviewLoading && overview == null)

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col gap-4', className)}>
      <AppPanel className="flex h-24 shrink-0 items-center gap-12 px-5">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 className="text-xl font-semibold leading-7 text-foreground">
            {hasTickets ? 'План работ составлен' : 'Создайте план работ'}
          </h2>
          {hasTickets ? (
            <p className="min-w-0 text-sm leading-6 text-[#71717a]">
              Расписание и маршруты инженеров доступны в{' '}
              <Link
                to={routes.planGantt}
                className="font-medium text-[#0485f7] hover:underline"
              >
                плане работ
              </Link>
            </p>
          ) : (
            <p className="truncate text-sm leading-6 text-[#71717a]">
              Загрузите заявки для региона «{regionLabel}»
            </p>
          )}
        </div>

        <div className="flex min-w-0 flex-1 gap-4">
          <SummaryCounter
            value={overview?.tickets.assigned ?? 0}
            total={overview?.tickets.total ?? 0}
            label="заявок назначено"
          />
          <SummaryCounter
            value={overview?.engineers.engaged ?? 0}
            total={overview?.engineers.total ?? 0}
            label="инженеров задействовано"
          />
        </div>
      </AppPanel>

      <div className="flex min-h-0 flex-1 gap-4">
        <AppPanel className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {hasTickets && regionId != null ? (
            <TicketsPanel regionId={regionId} date={date} planId={planId} />
          ) : showUploader ? (
            <>
              <PanelHeading
                title="Нет ни одной заявки"
                description="Загрузите заявки для начала работы алгоритма"
              />
              <TicketsDropzone isUploading={isUploading} onFiles={onFiles} />
            </>
          ) : (
            <PanelHeading title="Заявки" description="Загрузка" />
          )}
        </AppPanel>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          <AppPanel className="flex min-h-0 min-w-0 flex-1 basis-0 flex-col overflow-hidden">
            <EngineersPanel regionId={regionId} />
          </AppPanel>

          {hasTickets ? (
            <AppPanel className="flex min-h-0 min-w-0 flex-1 basis-0 flex-col overflow-hidden">
              <DayPlanPreview rows={planRowsFromTickets(chartTickets)} />
            </AppPanel>
          ) : (
            <AppPanel className="relative aspect-[515/208] w-full shrink-0 overflow-hidden">
              <img
                src={beesPromo}
                alt="Наши пчелки распределят заявки — а ты станешь не нужен!"
                className="absolute inset-0 size-full object-cover"
                draggable={false}
              />
            </AppPanel>
          )}
        </div>
      </div>
    </div>
  )
}
