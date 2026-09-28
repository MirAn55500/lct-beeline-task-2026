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
  MOCK_MAP_DATE,
  MOCK_MAP_REGIONS,
  PlanCompareDialog,
  PlanRebuildDialog,
  useDayOverview,
  useRecalculatePlanMutation,
} from '@/features/planning'
import { isOfflineError } from '@/features/planning/lib/offline'
import type { PlanComparison } from '@/features/planning'
import { TicketsUploadDialog, useTicketsExport } from '@/features/tickets'
import { ASIDE_WIDTH_CLASS, cn } from '@/shared/lib'
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
}

function readDateParam(raw: string | null): CalendarDate | null {
  if (!raw) return null
  try {
    return parseDate(raw)
  } catch {
    return null
  }
}

export function HomeAreaLayout({ children }: HomeAreaLayoutProps) {
  const [params, setParams] = useSearchParams()
  const regionsQuery = useGetRegionsQuery()
  const offline = isOfflineError(regionsQuery.isError, regionsQuery.error)
  const regions = offline ? MOCK_MAP_REGIONS : (regionsQuery.data ?? [])
  const isLoading = regionsQuery.isLoading
  const isError = regionsQuery.isError && !offline
  const [regionId, setRegionId] = useState<number | null>(null)
  const [planId, setPlanId] = useState<number | null>(null)
  const [recalculatePlan, { isLoading: isRecalculating }] = useRecalculatePlanMutation()
  const exportTickets = useTicketsExport()
  const [uploadOpen, setUploadOpen] = useState(false)
  const [rebuildOpen, setRebuildOpen] = useState(false)
  const [comparison, setComparison] = useState<PlanComparison | null>(null)

  const date =
    readDateParam(params.get('date')) ??
    (offline ? parseDate(MOCK_MAP_DATE) : today(getLocalTimeZone()))

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

  // Переспрашивается, пока план считается в фоне: индикатор в шапке и обновление по готовности
  const { data: overview } = useDayOverview(
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
    <div className="flex h-svh gap-4 bg-background p-4">
      <aside className={cn('flex shrink-0 flex-col gap-4', ASIDE_WIDTH_CLASS)}>
        <BrandBar className="w-full" />
        <AppNav />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <ContextHeader
          regions={regions}
          regionId={regionId}
          onRegionIdChange={selectRegion}
          date={date}
          onDateChange={setDate}
          plannedDates={overview?.planned_dates ?? []}
          plans={plans}
          planId={selectedPlanId}
          onPlanIdChange={setPlanId}
          isRegionsLoading={isLoading}
          isRegionsError={isError}
          onUploadClick={() => setUploadOpen(true)}
          isRecalculating={isRecalculating}
          isPlanning={overview?.planning ?? false}
          planningSeconds={overview?.planning_eta_seconds ?? null}
          onRecalculate={
            regionId == null ? undefined : () => setRebuildOpen(true)
          }
          onExport={
            regionId == null || selectedPlanId == null
              ? undefined
              : (format) =>
                  exportTickets(
                    { regionId, date: date.toString(), planId: selectedPlanId, offline },
                    format,
                    `Заявки_${regionName ?? regionId}_${date.toString()}`,
                  )
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
            const result = await recalculatePlan({
              regionId,
              date: date.toString(),
              remakeLevel: options.level,
              distribution: options.distribution,
              compare: options.distribution === 'efficient',
            }).unwrap()
            setPlanId(null)
            if (result.comparison) setComparison(result.comparison)
            else {
              toast.success(`План №${result.version} составлен`, {
                description: `Назначено ${result.assigned}, без инженера: ${result.unassigned}`,
              })
            }
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
                : 'Текущий план остался без изменений'
            toast.danger('Не удалось обновить план', { description })
          }
        }}
      />
      <PlanCompareDialog comparison={comparison} onClose={() => setComparison(null)} />
    </div>
  )
}
