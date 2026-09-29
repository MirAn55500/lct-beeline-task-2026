import type { EngineerRoute, LngLat, MapEngineer, RouteLeg } from '../mapTypes'

type PlanRouteGeometry = {
  /** "ors" — всё по улицам, "mixed" — часть участков прямые, "straight" — линии нет. */
  geometrySource: string
  /** Старт и точки визитов по порядку; место обеда — если к нему своя дорога. */
  polyline: LngLat[]
  geometry: LngLat[]
  visits: { geometryRange: [number, number] | null }[]
  lunch?: { afterPosition: number; detour: boolean; geometryRange: [number, number] | null } | null
}

const samePoint = (a: LngLat | undefined, b: LngLat | undefined) =>
  a != null && b != null && a[0] === b[0] && a[1] === b[1]

/**
 * Участки маршрута по визитам — срезы geometry по geometry_range.
 * Непостроенный участок планировщик вшивает в geometry прямой из двух точек маршрута
 * (planner/ors.py, _apply_geometry), а без геометрии вовсе остаётся только polyline.
 */
export function planRouteLegs(route: PlanRouteGeometry): RouteLeg[] {
  // Обед со своей дорогой — лишняя точка в polyline: визиты после него сдвигаются на одну
  const lunch = route.lunch?.detour ? route.lunch : null
  return route.visits.map((visit, index) =>
    legOf(route, index + (lunch && index >= lunch.afterPosition ? 1 : 0), visit.geometryRange),
  )
}

/** Дорога к месту обеда; null — обедают там, где закончили работу. */
export function planLunchLeg(route: PlanRouteGeometry): RouteLeg | null {
  const lunch = route.lunch
  if (!lunch?.detour) return null
  return legOf(route, lunch.afterPosition, lunch.geometryRange)
}

/** Участок от точки polyline[`from`] до следующей — по срезу geometry или прямой. */
function legOf(route: PlanRouteGeometry, from: number, range: [number, number] | null): RouteLeg {
  const a = route.polyline[from]
  const b = route.polyline[from + 1]
  if (route.geometrySource === 'straight' || !range || route.geometry.length < 2) {
    return { line: a && b ? [a, b] : [], straight: true }
  }
  const [start, end] = range
  const line = route.geometry.slice(start, end + 1)
  const straight =
    route.geometrySource === 'mixed' && line.length === 2 && samePoint(line[0], a) && samePoint(line[1], b)
  return { line, straight }
}

/** Прямая для заявки, добавленной вручную, пока планировщик не пересчитал путь. */
export const straightLeg = (from: LngLat, to: LngLat): RouteLeg => ({
  line: [from, to],
  straight: true,
})

/** Все точки маршрута одним списком — для fitBounds. */
export function routeCoordinates(engineer: MapEngineer, route: EngineerRoute | undefined): LngLat[] {
  return [
    engineer.start.coord,
    ...(route?.stops ?? []).flatMap((stop) => [...stop.leg.line, stop.coord]),
    ...(route?.lunch?.leg ? [...route.lunch.leg.line, route.lunch.coord] : []),
  ]
}
