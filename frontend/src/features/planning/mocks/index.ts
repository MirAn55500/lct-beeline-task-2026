/**
 * Моки страницы «План работ → Карта» — оптимизированные планы планировщика по трём регионам
 * из solution/viz/data/*.json (пересобрать: npm run mocks:map).
 * Заменить на API плана, когда карта пойдёт в бэк.
 */

import { planRouteLegs } from '../lib/routeGeometry'
import type {
  EngineerRoute,
  LngLat,
  MapEngineer,
  MapTicket,
  MapTransport,
  UnassignedReason,
  UnassignedTicket,
} from '../mapTypes'
import annaSmirnova from './avatars/anna-smirnova.jpg'
import ivanPetrov from './avatars/ivan-petrov.jpg'
import pavelKozlov from './avatars/pavel-kozlov.jpg'
import sashaBelyi from './avatars/sasha-belyi.jpg'
import planEast from './plan-east.json'
import planSoutheast from './plan-southeast.json'
import planSouthcentral from './plan-southcentral.json'

export type PlanExport = {
  key: string
  region: string
  date: string
  engineers: {
    id: string
    name: string
    start: LngLat
    workIntervals: [string, string][]
    skills: string[]
    skillLevels: [string, string][]
    transport: 'car' | 'walking' | 'bicycle' | 'public_transport'
    equipment: string[]
  }[]
  requests: {
    id: string
    point: LngLat
    window: [string, string]
    address: string
    type: string
    skill: string
    duration: number
    equipment: string[]
  }[]
  routes: {
    engineerId: string
    startAt: string | null
    endAt: string | null
    utilization: number
    geometrySource: string
    polyline: LngLat[]
    geometry: LngLat[]
    visits: {
      requestId: string
      geometryRange: [number, number] | null
      departureAt: string
      arrivalAt?: string
      serviceStartAt: string
      serviceEndAt: string
      /** Есть в ответе backend; в старых выгрузках — нет, берём от выезда до начала работ. */
      travelMinutes?: number
      distanceKm?: number
      transit: string[]
    }[]
  }[]
  unassigned: { requestId: string; reason: UnassignedReason; explanation: string }[]
}

export const PLANS = [planEast, planSoutheast, planSouthcentral] as unknown as PlanExport[]

export type MapRegion = {
  id: number
  name: string
}

export type MapPlan = {
  id: number
  version: number
  createdAt: string
}

/** Всё, что показывает карта по одному региону. */
export type MapDataset = {
  date: string
  engineers: MapEngineer[]
  routes: EngineerRoute[]
  unassigned: UnassignedTicket[]
}

export const MOCK_MAP_REGIONS: MapRegion[] = PLANS.map((plan, index) => ({
  id: index + 1,
  name: plan.region,
}))

export const MOCK_MAP_DATE = PLANS[0]!.date

export const MOCK_MAP_PLANNED_DATES = [...new Set(PLANS.map((plan) => plan.date))]

export const MOCK_MAP_PLANS: MapPlan[] = [
  { id: 1, version: 1, createdAt: `${MOCK_MAP_DATE}T07:30:00+03:00` },
  { id: 2, version: 2, createdAt: `${MOCK_MAP_DATE}T08:15:00+03:00` },
]

/** Стартовый вид карты до fitBounds — юго-восток Москвы, где лежат маршруты регионов. */
export const MAP_DEFAULT_VIEW = {
  center: [37.76, 55.71] as [number, number],
  zoom: 11.9,
}

/** Короткие подписи причин для тега на карточке; полный текст — в explanation. */
export const UNASSIGNED_REASON_LABEL: Record<UnassignedReason, string> = {
  no_engineers: 'Нет свободного инженера',
  no_region: 'Нет инженера в регионе',
  no_skill: 'Нет инженера с нужным навыком',
  no_transport: 'Нет инженера с нужным транспортом',
  no_equipment: 'Нет требуемого снаряжения',
  no_work_time: 'Нет рабочего времени',
  time_conflict: 'Не помещается в график',
  not_found: 'Вариант не найден',
  manual: 'Снята вручную',
}

// Палитра маршрутов: первые пять — из макета, дальше — в той же гамме.
const ROUTE_COLORS = [
  '#84cc16',
  '#22c55e',
  '#14b8a6',
  '#06b6d4',
  '#3b82f6',
  '#6366f1',
  '#a855f7',
  '#ec4899',
  '#f97316',
  '#eab308',
]

// Фото из макета — у первых инженеров, остальным хватит инициалов.
const AVATARS = [sashaBelyi, annaSmirnova, pavelKozlov, ivanPetrov]

// В выгрузке у старта только координаты; адрес базы «Востока» — из макета.
const START_ADDRESS: Record<string, string> = {
  east: 'ул. Юных Ленинцев, д. 83, стр. 4',
}

const TRANSPORT: Record<PlanExport['engineers'][number]['transport'], MapTransport> = {
  car: 'car',
  walking: 'walking',
  bicycle: 'bike',
  public_transport: 'public',
}

// Подписи квалификации — как на странице «Персонал».
export const LEVEL_LABEL: Record<string, string> = {
  senior: 'Мастер',
  middle: 'Бывалый',
  junior: 'Новичок',
}
const LEVEL_ORDER = ['junior', 'middle', 'senior']

/** «2026-08-17T09:05:00+03:00» → «9:05» — время уже в поясе региона. */
function clock(iso: string | null | undefined) {
  if (!iso) return ''
  return iso.slice(11, 16).replace(/^0/, '')
}

function minutesBetween(from: string, to: string) {
  return Math.max(0, Math.round((Date.parse(to) - Date.parse(from)) / 60000))
}

/** «Город Москва, ул.Михайлова, д. 14» → «ул. Михайлова, д. 14». */
export function shortAddress(address: string) {
  return address
    .replace(/^(Город\s+)?Москва,\s*/i, '')
    .replace(/\.(?=[А-ЯЁA-Z0-9])/g, '. ')
}

/**
 * Всё для карты из одного плана — моковой выгрузки или ответа `/api/planning/plan`.
 * Фото из макета — только у моков: реальным инженерам хватит инициалов.
 */
export function buildMapDataset(plan: PlanExport, { mock = false }: { mock?: boolean } = {}): MapDataset {
  const requestById = new Map(plan.requests.map((request) => [request.id, request]))
  const routeByEngineer = new Map(plan.routes.map((route) => [route.engineerId, route]))

  const toTicket = (requestId: string): MapTicket => {
    const request = requestById.get(requestId)!
    return {
      id: request.id,
      typeLabel: request.type,
      address: shortAddress(request.address),
      coord: request.point,
      window: `${clock(request.window[0])}–${clock(request.window[1])}`,
      needsRouter: request.equipment.includes('router'),
      needsBox: request.equipment.includes('set_top_box'),
    }
  }

  const engineers = plan.engineers.map((engineer, index): MapEngineer => {
    const route = routeByEngineer.get(engineer.id)
    const level = engineer.skillLevels
      .map(([, value]) => value)
      .sort((a, b) => LEVEL_ORDER.indexOf(b) - LEVEL_ORDER.indexOf(a))[0]
    const visitIds = route?.visits.map((visit) => visit.requestId) ?? []
    const needed = (kind: string) =>
      visitIds.filter((id) => requestById.get(id)?.equipment.includes(kind)).length
    const intervals = engineer.workIntervals
    return {
      id: engineer.id,
      name: engineer.name,
      avatarUrl: mock ? AVATARS[index] : undefined,
      transport: TRANSPORT[engineer.transport],
      qualification: LEVEL_LABEL[level ?? ''] ?? 'Инженер',
      routeFrom: clock(route?.startAt ?? intervals[0]?.[0]),
      routeTo: clock(route?.endAt ?? intervals[intervals.length - 1]?.[1]),
      shift: `${clock(intervals[0]?.[0])}–${clock(intervals[intervals.length - 1]?.[1])}`,
      load: Math.round((route?.utilization ?? 0) * 100),
      color: ROUTE_COLORS[index % ROUTE_COLORS.length]!,
      // В выгрузке только наличие снаряжения — количество в машине моковое.
      routers: engineer.equipment.includes('router') ? needed('router') + 2 : 0,
      boxes: engineer.equipment.includes('set_top_box') ? needed('set_top_box') + 1 : 0,
      start: { address: START_ADDRESS[plan.key] ?? 'Старт маршрута', coord: engineer.start },
    }
  })

  const routes = plan.routes.map((route): EngineerRoute => {
    const legs = planRouteLegs(route)
    return {
      engineerId: route.engineerId,
      stops: route.visits.map((visit, index) => ({
        ...toTicket(visit.requestId),
        leg: legs[index]!,
        transit: visit.transit,
        travelMinutes: visit.travelMinutes ?? minutesBetween(visit.departureAt, visit.arrivalAt ?? visit.serviceStartAt),
        distanceKm: visit.distanceKm,
      })),
    }
  })

  const unassigned = plan.unassigned.map(
    (item): UnassignedTicket => ({
      ...toTicket(item.requestId),
      reason: item.reason,
      explanation: item.explanation,
    }),
  )

  return { date: plan.date, engineers, routes, unassigned }
}

const DATASETS = new Map(MOCK_MAP_REGIONS.map((region, index) => [region.id, buildMapDataset(PLANS[index]!, { mock: true })]))

/** План региона на моках; неизвестный регион — первый из списка. */
export function getMapDataset(regionId: number | null): MapDataset {
  return DATASETS.get(regionId ?? 0) ?? DATASETS.get(MOCK_MAP_REGIONS[0]!.id)!
}
