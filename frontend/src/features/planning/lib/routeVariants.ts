import type { EngineerRoute, MapEngineer, MapTransport } from '../mapTypes'
import { estimateMinutes, legSteps, shiftClock, type RouteStep } from './routeSteps'

/** Вариант маршрута в окне «Параметры маршрута»: те же заявки в том же порядке, другой транспорт. */
export type RouteVariant = {
  transport: MapTransport
  /** Маршрут из плана; остальные варианты — оценка по расстоянию, планировщик их не считал. */
  current: boolean
  /** Шаги каждого участка: от старта до первой заявки, от первой до второй… */
  legs: RouteStep[][]
  totalMinutes: number
  /** Когда инженер закончит последнюю заявку, «18:02». */
  endsAt: string
}

export const ROUTE_TRANSPORTS: MapTransport[] = ['car', 'public', 'bike', 'walking']

/**
 * Варианты маршрута для выбранного транспорта, от быстрого к медленному.
 * Текущий — с шагами планировщика; для другого транспорта время участков оцениваем,
 * а окончание сдвигаем на разницу во времени в пути.
 */
export function routeVariants(engineer: MapEngineer, route: EngineerRoute, transports: MapTransport[]): RouteVariant[] {
  const currentTotal = route.stops.reduce((sum, stop) => sum + stop.travelMinutes, 0)

  return transports
    .map((transport): RouteVariant => {
      if (transport === engineer.transport) {
        return {
          transport,
          current: true,
          legs: route.stops.map((stop) => legSteps(stop.transit, transport, stop.travelMinutes)),
          totalMinutes: Math.round(currentTotal),
          endsAt: engineer.routeTo,
        }
      }
      const minutes = route.stops.map((stop, index) =>
        estimateMinutes(route.stops[index - 1]?.coord ?? engineer.start.coord, stop.coord, transport, stop.distanceKm),
      )
      const total = minutes.reduce((sum, value) => sum + value, 0)
      return {
        transport,
        current: false,
        legs: minutes.map((value) => legSteps([], transport, value)),
        totalMinutes: total,
        endsAt: engineer.routeTo ? shiftClock(engineer.routeTo, total - currentTotal) : '',
      }
    })
    .sort((a, b) => a.totalMinutes - b.totalMinutes)
}
