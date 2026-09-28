import { Link } from 'react-router'

import beesPromo from '@/shared/assets/day-overview-bees-promo.png'
import { TicketsDropzone, TicketsPanel } from '@/features/tickets'
import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import { useDayOverview } from '../lib/useDayOverview'
import { getOverviewPlanRows, getPlanMetrics } from '../lib/planMetrics'
import { useGetPlanExportQuery } from '../planApi'
import { DayPlanPreview } from './DayPlanPreview'

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
      <p className="text-sm leading-6 text-muted">{description}</p>
    </div>
  )
}

function MetricCard({
  value,
  suffix,
  label,
}: {
  value: string | number
  suffix?: string
  label: string
}) {
  return (
    <div className="flex h-20 min-w-0 flex-col justify-between rounded-lg bg-background px-3 py-2">
      <div className="flex items-baseline gap-1 text-4xl font-semibold leading-10 text-foreground">
        <span>{value}</span>
        {suffix ? <span className="text-base leading-6">{suffix}</span> : null}
      </div>
      <p className="truncate text-sm leading-5 text-foreground">{label}</p>
    </div>
  )
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
  const { data: overview, isFetching: overviewLoading } = useDayOverview(
    { regionId: regionId ?? 0, date, planId },
    { skip: regionId == null || date === '' },
  )
  const hasTickets = (overview?.tickets.total ?? 0) > 0
  const { data: plan } = useGetPlanExportQuery(
    { regionId: regionId ?? 0, date, planId },
    { skip: !overview?.has_plan || regionId == null || !date },
  )
  const metrics = getPlanMetrics(plan)
  const planRows = getOverviewPlanRows(plan)
  const regionLabel = regionName ?? '—'
  // Гант и карта откроются на том же регионе, дне и версии плана.
  const planLink = {
    pathname: routes.planGantt,
    search: new URLSearchParams({
      ...(regionId != null ? { region: String(regionId) } : {}),
      ...(date ? { date } : {}),
      ...(planId != null ? { plan: String(planId) } : {}),
    }).toString(),
  }
  const showUploader = !hasTickets && !(overviewLoading && overview == null)

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col gap-4', className)}>
      <AppPanel className="shrink-0 px-5 py-5">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-xl font-semibold leading-7 text-foreground">Текущий план</h2>
          {overview?.has_plan ? (
            <Link
              to={planLink}
              className="inline-flex h-9 items-center rounded-lg bg-accent px-4 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent-hover"
            >
              Перейти к плану
            </Link>
          ) : null}
        </div>
        {overview?.has_plan ? (
          <div className="grid grid-cols-3 gap-2">
            <MetricCard value={metrics?.assigned ?? overview.tickets.assigned ?? 0} label="Заявок назначено" />
            <MetricCard value={metrics?.unassigned ?? Math.max(0, overview.tickets.total - (overview.tickets.assigned ?? 0))} label="Заявки не назначено" />
            <MetricCard value={metrics?.engaged ?? overview.engineers.engaged ?? 0} suffix={`из ${metrics?.engineers ?? overview.engineers.total}`} label="Инженеров задействовано" />
            <MetricCard value={metrics?.averageTravelMinutes ?? 0} suffix="мин" label="Среднее время в пути" />
            <MetricCard value={`${metrics?.averageLoad ?? 0}%`} label="Средняя загрузка" />
          </div>
        ) : (
          <p className="py-4 text-sm leading-6 text-muted">
            Загрузите заявки для региона «{regionLabel}», чтобы составить план
          </p>
        )}
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

        {hasTickets ? (
          <AppPanel className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <DayPlanPreview rows={planRows} title="График" showLink={false} planLink={planLink} />
          </AppPanel>
        ) : (
          <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
            <AppPanel className="relative min-h-0 w-full flex-1 overflow-hidden">
              <img
                src={beesPromo}
                alt="Наши пчелки распределят заявки — а ты станешь не нужен!"
                className="absolute inset-0 size-full object-cover"
                draggable={false}
              />
            </AppPanel>
          </div>
        )}
      </div>
    </div>
  )
}
