import { Link } from 'react-router'
import { skipToken } from '@reduxjs/toolkit/query/react'

import beesPromo from '@/shared/assets/day-overview-bees-promo.png'
import { EngineersPanel } from '@/features/personnel'
import { TicketsDropzone, TicketsPanel } from '@/features/tickets'
import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'
import { formatWait } from '@/shared/lib/format'
import { AppPanel } from '@/shared/ui'

import { avgDistance, avgLoad, avgTravel, formatKm } from '../lib/planMetrics'
import { useDayOverview } from '../lib/useDayOverview'
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

/** Метрика текущего плана по макету: крупное число, мелкая единица, подпись. */
function MetricCard({ value, unit, label }: { value: string; unit?: string; label: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 bg-surface-secondary px-3 py-2" style={{ borderRadius: 12 }}>
      <p className="flex items-baseline gap-1 truncate text-foreground">
        <span className="text-4xl font-semibold leading-10">{value}</span>
        {unit ? <span className="text-xl font-semibold leading-7">{unit}</span> : null}
      </p>
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
  const hasPlan = overview?.has_plan ?? false
  const planning = overview?.planning ?? false
  const planningError = overview?.planning_error ?? null
  const planningSeconds = overview?.planning_eta_seconds ?? null
  // Об окончании фонового расчёта скажет тост из getDayOverview — один на все экраны
  // График и метрики — из той же выгрузки версии, что Гант и карта: время работ, дорога, обеды
  const planQuery = useGetPlanExportQuery(
    hasTickets && hasPlan && regionId != null ? { regionId, date, planId } : skipToken,
  )
  const plan = planQuery.currentData ?? (planQuery.isFetching ? planQuery.data : undefined)
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

  const assigned = overview?.tickets.assigned ?? 0
  const unassigned = plan ? plan.unassigned.length : Math.max(0, (overview?.tickets.total ?? 0) - assigned)
  const travel = avgTravel(plan)
  const load = avgLoad(plan)
  const kmPerTicket = avgDistance(plan)

  const title = hasPlan
    ? 'Текущий план'
    : planning
      ? 'Составляем план работ'
      : planningError
        ? 'План работ не составлен'
        : hasTickets
          ? 'Плана пока нет'
          : 'Создайте план работ'
  const status = planning
    ? `Распределяем заявки по инженерам${planningSeconds != null ? ` — осталось ${formatWait(planningSeconds)}` : ''}`
    : planningError
      ? planningError
      : hasPlan
        ? null
        : hasTickets
          ? 'Составьте план кнопкой «Обновить план»'
          : `Загрузите заявки для региона «${regionLabel}»`

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col gap-4', className)}>
      <AppPanel data-onboarding="overview-summary" className="flex shrink-0 flex-col gap-5 p-5">
        <div className="flex items-center justify-between gap-5">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="text-xl font-semibold leading-7 text-foreground">{title}</h2>
            {status ? <p className="truncate text-sm leading-6 text-muted">{status}</p> : null}
          </div>
          {hasPlan ? (
            <Link
              to={planLink}
              className="inline-flex h-9 shrink-0 cursor-pointer items-center bg-accent px-4 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent-hover"
              style={{ borderRadius: 8 }}
            >
              Перейти к плану
            </Link>
          ) : null}
        </div>

        {hasPlan ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <MetricCard value={String(assigned)} label="Заявок назначено" />
            <MetricCard value={String(unassigned)} label="Заявки не назначено" />
            <MetricCard
              value={String(overview?.engineers.engaged ?? 0)}
              unit={`из ${overview?.engineers.total ?? 0}`}
              label="Инженеров задействовано"
            />
            <MetricCard value={travel != null ? String(travel) : '—'} unit={travel != null ? 'мин' : undefined} label="Среднее время в пути" />
            <MetricCard value={load != null ? `${load}%` : '—'} label="Средняя загрузка" />
            <MetricCard
              value={kmPerTicket != null ? formatKm(kmPerTicket) : '—'}
              unit={kmPerTicket != null ? 'км' : undefined}
              label="Среднее на заявку"
            />
          </div>
        ) : null}
      </AppPanel>

      <div className="flex min-h-0 flex-1 gap-4">
        <AppPanel
          data-onboarding="overview-tickets"
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
        >
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
          <AppPanel
            data-onboarding="overview-secondary"
            className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
          >
            <DayPlanPreview plan={plan} loading={planQuery.isFetching} />
          </AppPanel>
        ) : (
          <div
            data-onboarding="overview-secondary"
            className="flex min-h-0 min-w-0 flex-1 flex-col gap-4"
          >
            <AppPanel className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
              <EngineersPanel regionId={regionId} />
            </AppPanel>
            <AppPanel className="relative aspect-[515/208] w-full shrink-0 overflow-hidden">
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
