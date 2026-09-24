import { useSyncExternalStore } from 'react'
import { useSearchParams } from 'react-router'
import { parseDate, type CalendarDate } from '@internationalized/date'

import { MOCK_MAP_DATE, MOCK_MAP_PLANS, MOCK_MAP_REGIONS, type MapPlan } from '../mocks'

// Версии плана, «пересчитанные» на моках, — общие для Ганта и карты до перезагрузки страницы.
let plans: MapPlan[] = MOCK_MAP_PLANS
const listeners = new Set<() => void>()
const subscribePlans = (listener: () => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function addPlan(): MapPlan {
  const last = plans[plans.length - 1]
  const plan = { id: (last?.id ?? 0) + 1, version: (last?.version ?? 0) + 1, createdAt: new Date().toISOString() }
  plans = [...plans, plan]
  listeners.forEach((listener) => listener())
  return plan
}

function readDate(value: string | null): CalendarDate {
  if (value) {
    try {
      return parseDate(value)
    } catch {
      // Кривая дата в адресе — берём день из моков.
    }
  }
  return parseDate(MOCK_MAP_DATE)
}

/**
 * Регион, день и версия плана для Ганта и карты. Живут в адресе (?region=&date=&plan=),
 * поэтому переключение вида их не сбрасывает, а ссылку можно переслать.
 */
export function usePlanContext() {
  const [params, setParams] = useSearchParams()
  const allPlans = useSyncExternalStore(subscribePlans, () => plans)

  const requestedRegion = Number(params.get('region'))
  const regionId =
    MOCK_MAP_REGIONS.find((item) => item.id === requestedRegion)?.id ?? MOCK_MAP_REGIONS[0]?.id ?? null
  const date = readDate(params.get('date'))
  const requestedPlan = Number(params.get('plan'))
  const planId = allPlans.find((item) => item.id === requestedPlan)?.id ?? allPlans[0]?.id ?? null

  const update = (patch: Record<string, string>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(patch)) next.set(key, value)
        return next
      },
      { replace: true },
    )

  return {
    regionId,
    date,
    plans: allPlans,
    planId,
    /** Мок пересчёта: новая версия плана с теми же назначениями, сразу выбранная. */
    addPlan: () => {
      const plan = addPlan()
      update({ plan: String(plan.id) })
      return plan
    },
    setRegionId: (id: number) => update({ region: String(id) }),
    setDate: (value: CalendarDate) => update({ date: value.toString() }),
    setPlanId: (id: number) => update({ plan: String(id) }),
  }
}
