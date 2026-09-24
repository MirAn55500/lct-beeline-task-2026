import { useEffect, useState, type ReactNode } from 'react'
import {
  getLocalTimeZone,
  parseDate,
  today,
  type CalendarDate,
} from '@internationalized/date'
import { toast } from '@heroui/react'
import { useSearchParams } from 'react-router'

import { useGetRegionsQuery } from '@/features/catalogs'
import {
  RemakePlanModal,
  useGetDayOverviewQuery,
  useRecalculatePlanMutation,
  type PlanDistribution,
  type RemakeLevel,
} from '@/features/planning'
import { AppNav, AppPanel, BrandBar, ContextHeader } from '@/shared/ui'

export type HomeAreaContext = {
  regionId: number | null
  regionName: string | null
  date: string
  planId: number | null
  focusDay: (isoDate: string) => void
  setRegionId: (regionId: number) => void
}

type HomeAreaLayoutProps = {
  children?: ReactNode | ((context: HomeAreaContext) => ReactNode)
  isUploadDisabled?: boolean
  onUploadClick?: () => void
  isExportDisabled?: boolean
  onExportCsv?: () => void
  onExportJson?: () => void
}

function readDateParam(raw: string | null): CalendarDate | null {
  if (!raw) return null
  try {
    return parseDate(raw)
  } catch {
    return null
  }
}

export function HomeAreaLayout({
  children,
  isUploadDisabled,
  onUploadClick,
  isExportDisabled,
  onExportCsv,
  onExportJson,
}: HomeAreaLayoutProps) {
  const [params, setParams] = useSearchParams()
  const { data: regions = [], isLoading, isError } = useGetRegionsQuery()
  const [regionId, setRegionId] = useState<number | null>(null)
  const [planId, setPlanId] = useState<number | null>(null)
  const [remakeOpen, setRemakeOpen] = useState(false)
  const [recalculatePlan, { isLoading: isRecalculating }] =
    useRecalculatePlanMutation()

  const date =
    readDateParam(params.get('date')) ?? today(getLocalTimeZone())

  const setDate = (next: CalendarDate) => {
    setPlanId(null)
    setParams(
      (prev) => {
        const copy = new URLSearchParams(prev)
        copy.set('date', next.toString())
        return copy
      },
      { replace: true },
    )
  }

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
    setDate(parseDate(isoDate))
  }
  const selectRegion = (nextRegionId: number) => {
    setPlanId(null)
    setRegionId(nextRegionId)
  }

  const handleRemake = async (args: {
    remakeLevel: RemakeLevel
    distribution: PlanDistribution
  }) => {
    if (regionId == null) return
    try {
      const result = await recalculatePlan({
        regionId,
        date: date.toString(),
        remakeLevel: args.remakeLevel,
        distribution: args.distribution,
      }).unwrap()
      setPlanId(null)
      toast.success('План обновлён', {
        description: `Версия ${result.version}: назначено ${result.assigned}, без назначения ${result.unassigned}`,
      })
    } catch (error) {
      const description =
        error &&
        typeof error === 'object' &&
        'data' in error &&
        error.data &&
        typeof error.data === 'object' &&
        'detail' in error.data &&
        typeof (error.data as { detail: unknown }).detail === 'string'
          ? (error.data as { detail: string }).detail
          : 'Проверьте заявки и инженеров на выбранную дату'
      toast.danger('Не удалось обновить план', {
        description,
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => setRemakeOpen(true),
        },
      })
      throw error
    }
  }

  const content =
    typeof children === 'function'
      ? children({
          regionId,
          regionName,
          date: date.toString(),
          planId: selectedPlanId,
          focusDay,
          setRegionId: selectRegion,
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
            selectRegion(nextRegionId)
          }}
          date={date}
          onDateChange={setDate}
          plannedDates={overview?.planned_dates ?? []}
          plans={plans}
          planId={selectedPlanId}
          onPlanIdChange={setPlanId}
          isRegionsLoading={isLoading}
          isRegionsError={isError}
          isUploadDisabled={isUploadDisabled}
          onUploadClick={onUploadClick}
          isExportDisabled={isExportDisabled}
          onExportCsv={onExportCsv}
          onExportJson={onExportJson}
          isRecalculating={isRecalculating}
          onRecalculate={
            regionId == null
              ? undefined
              : () => {
                  if (!isRecalculating) setRemakeOpen(true)
                }
          }
        />
        <RemakePlanModal
          isOpen={remakeOpen}
          onOpenChange={setRemakeOpen}
          isSubmitting={isRecalculating}
          onSubmit={handleRemake}
        />
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          {content ?? <AppPanel className="min-h-0 flex-1" />}
        </div>
      </div>
    </div>
  )
}
