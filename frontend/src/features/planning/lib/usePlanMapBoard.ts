import { useState } from 'react'

import type { EngineerRoute, MapEngineer, RouteStop, UnassignedTicket } from '../mapTypes'
import { getMapDataset } from '../mocks'
import { straightLeg } from './routeGeometry'

/** Заявка, брошенная в маршрут: ждёт подтверждения перепланирования. */
export type PendingDrop = {
  ticket: UnassignedTicket
  engineerId: string
  /** Позиция среди заявок маршрута, 0 — сразу после старта. */
  index: number
}

// Моковая прибавка загрузки за вручную добавленную заявку.
const LOAD_PER_MANUAL_STOP = 8

/**
 * Состояние страницы карты на моках: выбор и наведение, маршруты и неназначенные заявки.
 * Когда появится API, маршруты и заявки придут из RTK Query, а перепланирование — мутацией.
 */
/** План региона на день; в другие дни плана нет — инженеры без маршрутов, как пустой Гант. */
function datasetFor(regionId: number | null, date: string) {
  const dataset = getMapDataset(regionId)
  if (date === dataset.date) return dataset
  return {
    ...dataset,
    engineers: dataset.engineers.map((engineer) => ({ ...engineer, load: 0, routeFrom: '', routeTo: '' })),
    routes: [],
    unassigned: [],
  }
}

export function usePlanMapBoard(regionId: number | null, date: string) {
  const viewKey = `${regionId}:${date}`
  const [loadedKey, setLoadedKey] = useState(viewKey)
  const [engineers, setEngineers] = useState<MapEngineer[]>(() => datasetFor(regionId, date).engineers)
  const [routes, setRoutes] = useState<EngineerRoute[]>(() => datasetFor(regionId, date).routes)
  const [unassigned, setUnassigned] = useState<UnassignedTicket[]>(
    () => datasetFor(regionId, date).unassigned,
  )
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [activeStopId, setActiveStopId] = useState<string | null>(null)
  const [pendingDrop, setPendingDrop] = useState<PendingDrop | null>(null)

  // Другой регион или день — другой план: сбрасываем всё прямо в рендере, без лишнего кадра со старыми данными.
  if (loadedKey !== viewKey) {
    const dataset = datasetFor(regionId, date)
    setLoadedKey(viewKey)
    setEngineers(dataset.engineers)
    setRoutes(dataset.routes)
    setUnassigned(dataset.unassigned)
    setSelectedId(null)
    setHoveredId(null)
    setActiveStopId(null)
    setPendingDrop(null)
  }

  const hasPlan = date === getMapDataset(regionId).date

  const selectedEngineer = engineers.find((item) => item.id === selectedId) ?? null
  const selectedRoute = routes.find((item) => item.engineerId === selectedId) ?? null

  const select = (engineerId: string | null) => {
    const next = engineerId === selectedId ? null : engineerId
    setSelectedId(next)
    setHoveredId(null)
    // Как в макете: у выбранного маршрута сразу раскрыта первая заявка.
    const route = routes.find((item) => item.engineerId === next)
    setActiveStopId(route?.stops[0]?.id ?? null)
  }

  const toggleStop = (stopId: string) =>
    setActiveStopId((current) => (current === stopId ? null : stopId))

  const confirmDrop = () => {
    if (!pendingDrop) return
    const { ticket, engineerId, index } = pendingDrop
    const engineer = engineers.find((item) => item.id === engineerId)
    if (!engineer) return

    // Пока планировщик не пересчитал путь, новые участки — прямые (серый пунктир).
    setRoutes((current) =>
      current.map((route) => {
        if (route.engineerId !== engineerId) return route
        const stops = [...route.stops]
        const previous = stops[index - 1]?.coord ?? engineer.start.coord
        const added: RouteStop = {
          id: ticket.id,
          typeLabel: ticket.typeLabel,
          address: ticket.address,
          coord: ticket.coord,
          window: ticket.window,
          needsRouter: ticket.needsRouter,
          needsBox: ticket.needsBox,
          leg: straightLeg(previous, ticket.coord),
          transit: [],
        }
        const next = stops[index]
        if (next) stops[index] = { ...next, leg: straightLeg(ticket.coord, next.coord), transit: [] }
        stops.splice(index, 0, added)
        return { ...route, stops }
      }),
    )
    setUnassigned((current) => current.filter((item) => item.id !== ticket.id))
    setEngineers((current) =>
      current.map((item) =>
        item.id === engineerId ? { ...item, load: Math.min(100, item.load + LOAD_PER_MANUAL_STOP) } : item,
      ),
    )
    setActiveStopId(ticket.id)
    setPendingDrop(null)
  }

  return {
    regionId,
    hasPlan,
    engineers,
    routes,
    unassigned,
    selectedId,
    selectedEngineer,
    selectedRoute,
    hoveredId,
    activeStopId,
    pendingDrop,
    select,
    hover: setHoveredId,
    toggleStop,
    requestDrop: setPendingDrop,
    cancelDrop: () => setPendingDrop(null),
    confirmDrop,
  }
}

export type PlanMapBoard = ReturnType<typeof usePlanMapBoard>
