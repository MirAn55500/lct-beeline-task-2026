import type { LngLat, MapTransport } from '../mapTypes'

/** Один шаг пути до заявки: пешком, поездка на транспорте или весь участок одним видом транспорта. */
export type RouteStep = {
  kind: 'walk' | 'metro' | 'bus' | 'tram' | 'train' | 'car' | 'bike' | 'public'
  /** Номер линии или маршрута на плашке: «7», «с799», «МЦД-3». */
  label?: string
  /** Цвет плашки: у метро — цвет линии. */
  color?: string
  minutes: number
}

// Линии метро Москвы → номер и цвет плашки, как в макете «Параметры маршрута».
const METRO_LINES: [RegExp, string, string][] = [
  [/Сокольническая/i, '1', '#ef4444'],
  [/Замоскворецкая/i, '2', '#22c55e'],
  [/Арбатско-Покровская/i, '3', '#2563eb'],
  [/Филёвская|Филевская/i, '4', '#38bdf8'],
  [/Большая кольцевая/i, '11', '#14b8a6'],
  [/Кольцевая/i, '5', '#92400e'],
  [/Калужско-Рижская/i, '6', '#f97316'],
  [/Таганско-Краснопресненская/i, '7', '#a855f7'],
  [/Калининская/i, '8', '#eab308'],
  [/Солнцевская/i, '8А', '#eab308'],
  [/Серпуховско-Тимирязевская/i, '9', '#71717a'],
  [/Люблинско-Дмитровская/i, '10', '#84cc16'],
  [/Бутовская/i, '12', '#94a3b8'],
  [/Некрасовская/i, '15', '#ec4899'],
  [/Троицкая/i, '16', '#0d9488'],
]

const RIDE_COLOR: Record<string, string> = { bus: '#22c55e', tram: '#ef4444', train: '#ec4899' }

/**
 * Шаг из строки планировщика (TransitLeg.title):
 * «пешком 15 мин», «метро Большая кольцевая линия от «Печатники», 4 ост., 11 мин»,
 * «автобус м74 от «Волжский бульвар, 49», 1 ост., 1 мин», «электричка МЦД-3 «…» от «…», 1 ост., 2 мин».
 */
export function parseTransitStep(title: string): RouteStep {
  const minutes = Number(/(\d+)\s*мин\.?\s*$/.exec(title)?.[1] ?? 0)
  if (/^пешком/i.test(title)) return { kind: 'walk', minutes }

  const metro = /^метро\s+(.+?)\s+от\s/i.exec(title)
  if (metro) {
    const line = METRO_LINES.find(([pattern]) => pattern.test(metro[1]!))
    return { kind: 'metro', label: line?.[1] ?? 'М', color: line?.[2] ?? '#71717a', minutes }
  }

  const ride = /^(автобус|троллейбус|трамвай|электричка|МЦД|МЦК)\s+(\S+)/i.exec(title)
  const kind: RouteStep['kind'] =
    ride?.[1] === 'трамвай' ? 'tram' : ride?.[1] === 'электричка' ? 'train' : ride ? 'bus' : 'public'
  const label = ride?.[2]?.replace(/[«»]/g, '')
  return { kind, label, color: RIDE_COLOR[kind] ?? '#71717a', minutes }
}

const TRANSPORT_STEP: Record<MapTransport, RouteStep['kind']> = {
  car: 'car',
  bike: 'bike',
  walking: 'walk',
  public: 'public',
}

/** Шаги участка: у общественного транспорта — поездки из планировщика, иначе весь путь одним видом. */
export function legSteps(transit: string[], transport: MapTransport, travelMinutes: number): RouteStep[] {
  if (transit.length > 0) return transit.map(parseTransitStep)
  return [{ kind: TRANSPORT_STEP[transport], minutes: Math.round(travelMinutes) }]
}

// Средняя скорость по городу с учётом светофоров и пересадок, км/ч.
const SPEED_KMH: Record<MapTransport, number> = { car: 24, public: 17, bike: 13, walking: 4.5 }
// Во сколько раз путь по улицам длиннее прямой.
const DETOUR = 1.35

function distanceKm([lng1, lat1]: LngLat, [lng2, lat2]: LngLat) {
  const rad = Math.PI / 180
  const dLat = (lat2 - lat1) * rad
  const dLng = (lng2 - lng1) * rad
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2
  return 12742 * Math.asin(Math.sqrt(a))
}

/** Оценка времени в пути другим видом транспорта — для вариантов, которые планировщик не считал. */
export function estimateMinutes(from: LngLat, to: LngLat, transport: MapTransport, distance?: number) {
  const km = distance ?? distanceKm(from, to) * DETOUR
  // На общественном транспорте добавляем дорогу до остановки и ожидание.
  const overhead = transport === 'public' ? 8 : 0
  return Math.max(1, Math.round((km / SPEED_KMH[transport]) * 60 + overhead))
}

/** «174» → «2 ч 54 мин». */
export function formatDuration(minutes: number) {
  const hours = Math.floor(minutes / 60)
  const rest = Math.round(minutes % 60)
  if (hours === 0) return `${rest} мин`
  return rest === 0 ? `${hours} ч` : `${hours} ч ${String(rest).padStart(2, '0')} мин`
}

/** «9:05» + 30 → «9:35». */
export function shiftClock(clock: string, delta: number) {
  const [hours = 0, minutes = 0] = clock.split(':').map(Number)
  const total = Math.max(0, Math.min(24 * 60 - 1, hours * 60 + minutes + Math.round(delta)))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
