import { useEffect, useState, type ReactNode } from 'react'
import {
  getLocalTimeZone,
  parseDate,
  today,
  type CalendarDate,
} from '@internationalized/date'

import { useGetRegionsQuery } from '@/features/catalogs'
import { useGetDayOverviewQuery, useRecalculatePlanMutation } from '@/features/planning'
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
  isUploadDisabled?: boolean
  onUploadClick?: () => void
}

export function HomeAreaLayout({
  children,
  isUploadDisabled,
  onUploadClick,
}: HomeAreaLayoutProps) {
  const { data: regions = [], isLoading, isError } = useGetRegionsQuery()
  const [regionId, setRegionId] = useState<number | null>(null)
  const [date, setDate] = useState<CalendarDate>(() => today(getLocalTimeZone()))
  const [planId, setPlanId] = useState<number | null>(null)
  const [recalculatePlan, { isLoading: isRecalculating }] = useRecalculatePlanMutation()
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
      <aside className="flex w-[346px] shrink-0 flex-col gap-4">
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
          isUploadDisabled={isUploadDisabled}
          onUploadClick={onUploadClick}
          isRecalculating={isRecalculating}
          onRecalculate={
            regionId == null
              ? undefined
              : async () => {
                  try {
                    await recalculatePlan({
                      regionId,
                      date: date.toString(),
                    }).unwrap()
                    setPlanId(null)
                  } catch {
                    // Ошибка расчёта оставляет текущий план.
                  }
                }
          }
        />
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          {content ?? <AppPanel className="min-h-0 flex-1" />}
        </div>
      </div>
    </div>
  )
}
