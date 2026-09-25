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
    const visits = [...(routeOf.get(engineer.id)?.visits ?? [])].sort(
      (a, b) => Date.parse(a.serviceStartAt) - Date.parse(b.serviceStartAt),
    )
    const first = visits[0]
    if (!first || now < Date.parse(first.departureAt)) {
      return { engineerId, coord: start, status: 'В офисе' }
    }

    let previous: Point = start
    for (const visit of visits) {
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
    const last = visits[visits.length - 1]!
    return { engineerId, coord: previous, status: `Закончил день на заявке №${last.requestId}` }
  })
}
