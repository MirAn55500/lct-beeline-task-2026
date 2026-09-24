import { useEffect, useState, type ReactNode } from 'react'
import {
  getLocalTimeZone,
  parseDate,
  today,
  type CalendarDate,
} from '@internationalized/date'

import { toast } from '@heroui/react'

import { useGetRegionsQuery } from '@/features/catalogs'
import {
  PlanRebuildDialog,
  useGetDayOverviewQuery,
  useRecalculatePlanMutation,
} from '@/features/planning'
import { TicketsUploadDialog, downloadTickets, useLazyGetTicketsQuery } from '@/features/tickets'
import { ASIDE_WIDTH_CLASS, cn } from '@/shared/lib'
import { AppNav, AppPanel, BrandBar, ContextHeader } from '@/shared/ui'

export type HomeAreaContext = {
  regionId: number | null
  regionName: string | null
  date: string
  planId: number | null
  focusDay: (isoDate: string) => void
}

type HomeAreaLayoutProps = {
  children?: ReactNode | ((context: HomeAreaContext) => ReactNode)
}

export function HomeAreaLayout({ children }: HomeAreaLayoutProps) {
  const { data: regions = [], isLoading, isError } = useGetRegionsQuery()
  const [regionId, setRegionId] = useState<number | null>(null)
  const [date, setDate] = useState<CalendarDate>(() => today(getLocalTimeZone()))
  const [planId, setPlanId] = useState<number | null>(null)
  const [recalculatePlan, { isLoading: isRecalculating }] = useRecalculatePlanMutation()
  const [loadTickets] = useLazyGetTicketsQuery()
  const [uploadOpen, setUploadOpen] = useState(false)
  const [rebuildOpen, setRebuildOpen] = useState(false)
  const { data: overview } = useGetDayOverviewQuery(
    { regionId: regionId ?? 0, date: date.toString(), planId },
    { skip: regionId == null },
  )

  useEffect(() => {
    if (regions.length === 0) {
      setRegionId(null)
      return
    }
    setRegionId((current) =>
      current != null && regions.some((item) => item.id === current)
        ? current
        : regions[0].id,
    )
  }, [regions])

  const regionName = regions.find((item) => item.id === regionId)?.name ?? null
  const plans = (overview?.plans ?? []).map((item) => ({
    id: item.plan_id,
    version: item.version,
    createdAt: item.created_at,
  }))
  const selectedPlanId = planId ?? overview?.plan_id ?? null
  const focusDay = (isoDate: string) => {
    setPlanId(null)
    setDate(parseDate(isoDate))
  }
  const content =
    typeof children === 'function'
      ? children({
          regionId,
          regionName,
          date: date.toString(),
          planId: selectedPlanId,
          focusDay,
        })
      : children

  return (
    <div className="flex h-svh gap-4 bg-[#f5f5f5] p-4">
      <aside className={cn('flex shrink-0 flex-col gap-4', ASIDE_WIDTH_CLASS)}>
        <BrandBar className="w-full" />
        <AppNav />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <ContextHeader
          regions={regions}
          regionId={regionId}
          onRegionIdChange={(nextRegionId) => {
            setPlanId(null)
            setRegionId(nextRegionId)
          }}
          date={date}
          onDateChange={(nextDate) => {
            setPlanId(null)
            setDate(nextDate)
          }}
          plannedDates={overview?.planned_dates ?? []}
          plans={plans}
          planId={selectedPlanId}
          onPlanIdChange={setPlanId}
          isRegionsLoading={isLoading}
          isRegionsError={isError}
          onUploadClick={() => setUploadOpen(true)}
          isRecalculating={isRecalculating}
          onRecalculate={regionId == null ? undefined : () => setRebuildOpen(true)}
          onExport={
            regionId == null || !overview?.tickets.total
              ? undefined
              : async (format) => {
                  try {
                    const tickets = await loadTickets({
                      regionId,
                      date: date.toString(),
                      planId: selectedPlanId,
                    }).unwrap()
                    downloadTickets(tickets, format, `Заявки_${regionName ?? regionId}_${date.toString()}`)
                  } catch {
                    toast.danger('Не удалось выгрузить заявки')
                  }
                }
          }
        />
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          {content ?? <AppPanel className="min-h-0 flex-1" />}
        </div>
      </div>

      <TicketsUploadDialog
        isOpen={uploadOpen}
        onClose={() => setUploadOpen(false)}
        defaultRegionId={regionId}
        date={date.toString()}
        onUploaded={(result) => {
          if (result.date) focusDay(result.date)
        }}
      />
      <PlanRebuildDialog
        isOpen={rebuildOpen}
        onClose={() => setRebuildOpen(false)}
        onConfirm={async (options) => {
          if (regionId == null) return
          try {
            const result = await recalculatePlan({ regionId, date: date.toString(), ...options }).unwrap()
            setPlanId(null)
            toast.success(`План №${result.version} составлен`, {
              description: `Назначено ${result.assigned}, без инженера: ${result.unassigned}`,
            })
          } catch {
            toast.danger('Не удалось обновить план', { description: 'Текущий план остался без изменений' })
          }
        }}
      />
    </div>
  )
}
