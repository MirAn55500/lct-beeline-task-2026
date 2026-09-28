import type { PlanExport } from '@/features/planning'

export type EngineerPosition = {
  engineerId: number
  /** [lng, lat] */
  coord: [number, number]
  /** Где инженер по плану: «На заявке №74198», «В пути к заявке №…», «В офисе». */
  status: string
}

type Point = [number, number]

const lerp = (from: Point, to: Point, t: number): Point => [
  from[0] + (to[0] - from[0]) * t,
  from[1] + (to[1] - from[1]) * t,
]

/**
 * Где сейчас инженеры по плану дня: на заявке, в пути между точками (по прямой,
 * пропорционально времени в пути) или в офисе — до выезда, без маршрута и после дня.
 * Живых координат у инженеров нет, поэтому это положение по расписанию.
 */
export function engineerPositions(
  plan: PlanExport,
  office: Point,
  now: number = Date.now(),
): EngineerPosition[] {
  const pointOf = new Map(plan.requests.map((request) => [request.id, request.point]))
  const routeOf = new Map(plan.routes.map((route) => [route.engineerId, route]))

  return plan.engineers.map((engineer) => {
    const engineerId = Number(engineer.id)
    const start = engineer.start ?? office
    const route = routeOf.get(engineer.id)
    const visits = [...(route?.visits ?? [])].sort(
      (a, b) => Date.parse(a.serviceStartAt) - Date.parse(b.serviceStartAt),
    )
    const lunch = route?.lunch ?? null
    const first = visits[0]

    // Обед — тоже остановка: к месту обеда едут, там ждут начала и обедают
    const atLunch = (from: Point): EngineerPosition | null => {
      if (!lunch) return null
      const departure = Date.parse(lunch.departureAt)
      const arrival = Date.parse(lunch.arrivalAt || lunch.startAt)
      const end = Date.parse(lunch.endAt)
      const place: Point = lunch.detour ? lunch.point : from
      if (now < departure || now >= end) return null
      if (now < arrival) {
        const t = arrival > departure ? Math.max(0, (now - departure) / (arrival - departure)) : 1
        return { engineerId, coord: lerp(from, place, t), status: 'Едет на обед' }
      }
      return { engineerId, coord: place, status: 'На обеде' }
    }
    // Обед до первой заявки: из офиса едут на обед, а не к заявке
    const lunchFirst = lunch != null && lunch.afterPosition === 0
    if (lunchFirst) {
      const found = atLunch(start)
      if (found) return found
    }
    if (!first || now < Date.parse(first.departureAt)) {
      const lunchOver = lunchFirst && lunch.detour && now >= Date.parse(lunch.endAt)
      return { engineerId, coord: lunchOver ? lunch.point : start, status: lunchOver ? 'После обеда' : 'В офисе' }
    }

    let previous: Point = lunchFirst && lunch.detour ? lunch.point : start
    for (const [index, visit] of visits.entries()) {
      if (lunch && index > 0 && lunch.afterPosition === index) {
        const found = atLunch(previous)
        if (found) return found
        if (lunch.detour && now >= Date.parse(lunch.endAt)) previous = lunch.point
      }
      const point = pointOf.get(visit.requestId) ?? previous
      const departure = Date.parse(visit.departureAt)
      const arrival = Date.parse(visit.arrivalAt ?? visit.serviceStartAt)
      if (now < departure) {
        return { engineerId, coord: previous, status: `Ждёт выезда к заявке №${visit.requestId}` }
      }
      if (now < arrival) {
        const t = arrival > departure ? Math.max(0, (now - departure) / (arrival - departure)) : 1
        return { engineerId, coord: lerp(previous, point, t), status: `В пути к заявке №${visit.requestId}` }
      }
      if (now < Date.parse(visit.serviceEndAt)) {
        return { engineerId, coord: point, status: `На заявке №${visit.requestId}` }
      }
      previous = point
    }
    if (lunch && lunch.afterPosition >= visits.length) {
      const found = atLunch(previous)
      if (found) return found
      if (lunch.detour && now >= Date.parse(lunch.endAt)) {
        return { engineerId, coord: lunch.point, status: 'Закончил день после обеда' }
      }
    }
    const last = visits[visits.length - 1]!
    return { engineerId, coord: previous, status: `Закончил день на заявке №${last.requestId}` }
  })
}
