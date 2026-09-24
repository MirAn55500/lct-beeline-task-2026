import type { EngineerRoute, LngLat, MapEngineer, RouteLeg } from '../mapTypes'

type PlanRouteGeometry = {
  /** "ors" — всё по улицам, "mixed" — часть участков прямые, "straight" — линии нет. */
  geometrySource: string
  /** Старт и точки визитов по порядку. */
  polyline: LngLat[]
  geometry: LngLat[]
  visits: { geometryRange: [number, number] | null }[]
}

const samePoint = (a: LngLat | undefined, b: LngLat | undefined) =>
  a != null && b != null && a[0] === b[0] && a[1] === b[1]

/**
 * Участки маршрута по визитам — срезы geometry по geometry_range.
 * Непостроенный участок планировщик вшивает в geometry прямой из двух точек маршрута
 * (planner/ors.py, _apply_geometry), а без геометрии вовсе остаётся только polyline.
 */
export function planRouteLegs(route: PlanRouteGeometry): RouteLeg[] {
  return route.visits.map((visit, index) => {
    const from = route.polyline[index]
    const to = route.polyline[index + 1]
    const straightLeg = (): RouteLeg => ({ line: from && to ? [from, to] : [], straight: true })

    if (route.geometrySource === 'straight' || !visit.geometryRange || route.geometry.length < 2) {
      return straightLeg()
    }
    const [start, end] = visit.geometryRange
    const line = route.geometry.slice(start, end + 1)
    const straight =
      route.geometrySource === 'mixed' &&
      line.length === 2 &&
      samePoint(line[0], from) &&
      samePoint(line[1], to)
    return { line, straight }
  })
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
  ]
}
