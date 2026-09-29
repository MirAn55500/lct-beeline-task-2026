import type { PlanExportResponse } from '../planApi'

/** Визиты к заявкам; отменённая в пути заявка — только поездка, не назначенная работа. */
export function planVisits(plan: PlanExportResponse | undefined) {
  return plan?.routes.flatMap((route) => route.visits.filter((visit) => !visit.cancelled)) ?? []
}

/** Средняя загрузка задействованных инженеров, %; без маршрутов — null. */
export function avgLoad(plan: PlanExportResponse | undefined): number | null {
  if (!plan?.routes.length) return null
  const active = plan.routes.filter((route) => route.visits.length > 0)
  const sample = active.length > 0 ? active : plan.routes
  if (sample.length === 0) return null
  const sum = sample.reduce((acc, route) => acc + route.utilization, 0)
  return Math.round((sum / sample.length) * 100)
}

/** Среднее время в пути до заявки, минуты; без визитов — null. */
export function avgTravel(plan: PlanExportResponse | undefined): number | null {
  const visits = planVisits(plan)
  if (visits.length === 0) return null
  return Math.round(visits.reduce((acc, visit) => acc + (visit.travelMinutes ?? 0), 0) / visits.length)
}

/** Пробег плана до заявок, км — сумма участков визитов. */
export function totalDistance(plan: PlanExportResponse | undefined): number | null {
  const visits = plan?.routes.flatMap((route) => route.visits) ?? []
  if (visits.length === 0) return null
  return visits.reduce((acc, visit) => acc + (visit.distanceKm ?? 0), 0)
}

/** Средний пробег на назначенную заявку, км. */
export function avgDistance(plan: PlanExportResponse | undefined): number | null {
  const total = totalDistance(plan)
  const visits = planVisits(plan).length
  return total != null && visits > 0 ? total / visits : null
}

/** «12,3» — километры с одним знаком, как в остальном интерфейсе. */
export function formatKm(value: number): string {
  return value.toFixed(1).replace('.', ',')
}
