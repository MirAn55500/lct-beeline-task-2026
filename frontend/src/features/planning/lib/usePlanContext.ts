import { useSyncExternalStore } from 'react'
import { useSearchParams } from 'react-router'
import { getLocalTimeZone, parseDate, today, type CalendarDate } from '@internationalized/date'
import { skipToken } from '@reduxjs/toolkit/query/react'
import { toast } from '@heroui/react'

import { useGetRegionsQuery } from '@/features/catalogs'

import { useRecalculatePlanMutation } from '../api'
import {
  MOCK_MAP_DATE,
  MOCK_MAP_PLANNED_DATES,
  MOCK_MAP_PLANS,
  MOCK_MAP_REGIONS,
  type MapPlan,
} from '../mocks'
import type { PlanDistribution, PlanRebuildLevel } from '../types'
import { isOfflineError } from './offline'
import { useCountdown } from './useCountdown'
import { useDayOverview } from './useDayOverview'

// Без backend версии плана «пересчитываются» на моках — общие для Ганта и карты до перезагрузки страницы.
let mockPlans: MapPlan[] = MOCK_MAP_PLANS
const listeners = new Set<() => void>()
const subscribeMockPlans = (listener: () => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function addMockPlan(): MapPlan {
  const last = mockPlans[mockPlans.length - 1]
  const plan = { id: (last?.id ?? 0) + 1, version: (last?.version ?? 0) + 1, createdAt: new Date().toISOString() }
  mockPlans = [...mockPlans, plan]
  listeners.forEach((listener) => listener())
  return plan
}

function readDate(value: string | null, fallback: CalendarDate): CalendarDate {
  if (value) {
    try {
      return parseDate(value)
    } catch {
      // Кривая дата в адресе — берём день по умолчанию.
    }
  }
  return fallback
}

/**
 * Регион, день и версия плана для Ганта и карты. Живут в адресе (?region=&date=&plan=),
 * поэтому переключение вида их не сбрасывает, а ссылку можно переслать.
 * Регионы — из справочника, версии и дни с планом — из `/api/planning/day-overview`;
 * без версии в адресе выбрана последняя. Если backend не поднят — всё на моках.
 */
export function usePlanContext() {
  const [params, setParams] = useSearchParams()
  const regionsQuery = useGetRegionsQuery()
  const offline = isOfflineError(regionsQuery.isError, regionsQuery.error)
  const allMockPlans = useSyncExternalStore(subscribeMockPlans, () => mockPlans)
  const [recalculatePlan, { isLoading: isRebuilding }] = useRecalculatePlanMutation()

  const regions = offline ? MOCK_MAP_REGIONS : (regionsQuery.data ?? [])
  const requestedRegion = Number(params.get('region'))
  const regionId = regions.find((item) => item.id === requestedRegion)?.id ?? regions[0]?.id ?? null
  // Без даты в адресе — сегодня, как на «Обзоре дня»; на моках — день из выгрузки.
  const date = readDate(params.get('date'), offline ? parseDate(MOCK_MAP_DATE) : today(getLocalTimeZone()))

  const overviewQuery = useDayOverview(
    !offline && regionId != null ? { regionId, date: date.toString() } : skipToken,
  )
  // Версии — только этого дня; дни с планом в календаре можно показывать и от прошлого ответа.
  const overview = overviewQuery.currentData
  const rebuildSeconds = useCountdown(isRebuilding, overview?.rebuild_eta_seconds ?? null)

  const plans: MapPlan[] = offline
    ? allMockPlans
    : (overview?.plans ?? []).map((item) => ({ id: item.plan_id, version: item.version, createdAt: item.created_at }))
  const requestedPlan = Number(params.get('plan'))
  const latestPlanId = offline ? (allMockPlans[allMockPlans.length - 1]?.id ?? null) : (overview?.plan_id ?? null)
  // Пока версии грузятся, верим адресу — иначе сначала придёт последняя версия, а потом нужная.
  const planId =
    plans.find((item) => item.id === requestedPlan)?.id ??
    (!offline && !overview && requestedPlan > 0 ? requestedPlan : latestPlanId)

  const update = (patch: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(patch)) {
          if (value == null) next.delete(key)
          else next.set(key, value)
        }
        return next
      },
      { replace: true },
    )

  /** «Обновить план»: пересчёт на backend и сразу новая версия; без backend — мок с теми же назначениями. */
  const rebuild = async (options: { level: PlanRebuildLevel; distribution: PlanDistribution }) => {
    if (offline) {
      const plan = addMockPlan()
      update({ plan: String(plan.id) })
      toast.success(`План №${plan.version} составлен`)
      return
    }
    if (regionId == null) return
    try {
      const result = await recalculatePlan({
        regionId,
        date: date.toString(),
        ...options,
      }).unwrap()
      update({ plan: String(result.plan_id) })
      toast.success(`План №${result.version} составлен`, {
        description: `Назначено ${result.assigned}, без инженера: ${result.unassigned}`,
      })
      return result
    } catch (error) {
      // Причину backend (например, «в этот день бригада не работает») показываем как есть
      const detail = (error as { data?: { detail?: unknown } } | null)?.data?.detail
      toast.danger('Не удалось обновить план', {
        description:
          typeof detail === 'string' && detail.trim()
            ? `${detail}. Текущий план остался без изменений`
            : 'Текущий план остался без изменений',
      })
    }
  }

  return {
    offline,
    regions,
    isRegionsLoading: regionsQuery.isLoading,
    isRegionsError: regionsQuery.isError && !offline,
    regionId,
    date,
    plannedDates: offline ? MOCK_MAP_PLANNED_DATES : (overviewQuery.data?.planned_dates ?? []),
    plans,
    planId,
    /** Версия для запроса плана: null — последняя, так у неё одна запись в кэше, пока грузятся версии. */
    queryPlanId: planId === latestPlanId ? null : planId,
    isRebuilding,
    rebuild,
    /** План дня считается в фоне после загрузки заявок и примерно сколько секунд осталось. */
    isPlanning: overview?.planning ?? false,
    planningSeconds: isRebuilding ? rebuildSeconds : (overview?.planning_eta_seconds ?? null),
    // Другой регион или день — другие версии плана: выбор версии сбрасываем.
    setRegionId: (id: number) => update({ region: String(id), plan: null }),
    setDate: (value: CalendarDate) => update({ date: value.toString(), plan: null }),
    setPlanId: (id: number) => update({ plan: String(id) }),
  }
}

export type PlanContext = ReturnType<typeof usePlanContext>
