import { toast } from '@heroui/react'
import { skipToken } from '@reduxjs/toolkit/query/react'
import { useMemo, useState } from 'react'

import type { EngineerRoute, MapEngineer, RouteStop, UnassignedTicket } from '../mapTypes'
import { buildMapDataset, getMapDataset, type MapDataset } from '../mocks'
import { useGetPlanExportQuery, useMovePlanRequestMutation } from '../planApi'
import { isOfflineError } from './offline'
import { straightLeg } from './routeGeometry'
import { estimateMinutes } from './routeSteps'
import type { RouteVariant } from './routeVariants'

/** Заявка, брошенная в маршрут: ждёт подтверждения перепланирования. */
export type PendingDrop = {
  ticket: UnassignedTicket
  engineerId: string
  /** Позиция среди заявок маршрута, 0 — сразу после старта. */
  index: number
}

// Моковая прибавка загрузки за вручную добавленную заявку.
const LOAD_PER_MANUAL_STOP = 8

type MapBoardDataset = Pick<MapDataset, 'engineers' | 'routes' | 'unassigned'>

const EMPTY: MapBoardDataset = { engineers: [], routes: [], unassigned: [] }

/** План региона на моках; в другие дни плана нет — инженеры без маршрутов, как пустой Гант. */
function mockDatasetFor(regionId: number | null, date: string): MapBoardDataset {
  const dataset = getMapDataset(regionId)
  if (date === dataset.date) return dataset
  return {
    engineers: dataset.engineers.map((engineer) => ({ ...engineer, load: 0, routeFrom: '', routeTo: '' })),
    routes: [],
    unassigned: [],
  }
}

/**
 * Состояние страницы карты: выбор и наведение, маршруты и неназначенные заявки.
 * План — из `/api/planning/plan` (выбранная версия, без неё — последняя), маршруты по улицам —
 * его geometry. Без плана на день карта пустая, как «work-area - map-layout»; без backend — моки.
 * Ручное добавление заявки сохраняется ходом планировщика. Без backend остаётся локальным.
 */
export function usePlanMapBoard(
  regionId: number | null,
  date: string,
  planId: number | null = null,
  /** `readOnly` — старая версия плана или прошедший день: руками не правится. */
  options?: { onSaved?: (planId: number) => void; readOnly?: boolean },
) {
  const query = useGetPlanExportQuery(regionId != null ? { regionId, date, planId } : skipToken)
  const offline = isOfflineError(query.isError, query.error)
  // Пока грузится другая версия, держим прежние маршруты, а не мигаем пустой картой.
  const plan = query.currentData ?? (query.isFetching ? query.data : undefined)
  const dataset = useMemo(
    () => (plan ? buildMapDataset(plan) : offline ? mockDatasetFor(regionId, date) : EMPTY),
    [plan, offline, regionId, date],
  )
  const hasPlan = plan ? true : offline && date === getMapDataset(regionId).date
  const viewKey = `${regionId}:${date}:${plan ? `plan-${plan.planId}` : offline ? 'mock' : 'none'}`

  const [loadedKey, setLoadedKey] = useState(viewKey)
  const [engineers, setEngineers] = useState<MapEngineer[]>(dataset.engineers)
  const [routes, setRoutes] = useState<EngineerRoute[]>(dataset.routes)
  const [unassigned, setUnassigned] = useState<UnassignedTicket[]>(dataset.unassigned)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [activeStopId, setActiveStopId] = useState<string | null>(null)
  const [pendingDrop, setPendingDrop] = useState<PendingDrop | null>(null)
  const [moveRequest, { isLoading: isSavingDrop }] = useMovePlanRequestMutation()

  // Другой регион, день или версия — другой план: сбрасываем всё прямо в рендере, без лишнего кадра со старыми данными.
  if (loadedKey !== viewKey) {
    setLoadedKey(viewKey)
    setEngineers(dataset.engineers)
    setRoutes(dataset.routes)
    setUnassigned(dataset.unassigned)
    setSelectedId(null)
    setHoveredId(null)
    setActiveStopId(null)
    setPendingDrop(null)
  }

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
    setPendingDrop(null)

    if (plan && !offline) {
      void moveRequest({
        planId: plan.planId,
        requestId: ticket.id,
        engineerId,
        position: index,
        commit: true,
      })
        .unwrap()
        .then((response) => {
          if (!response.ok) {
            toast.danger('Сюда не встанет', { description: response.reason })
            return
          }
          if (response.planId != null) options?.onSaved?.(response.planId)
          toast.success('Маршрут обновлён')
        })
        .catch((error: unknown) => {
          const detail = (error as { data?: { detail?: unknown } } | null)?.data?.detail
          toast.danger('Не удалось сохранить маршрут', {
            description: typeof detail === 'string' ? detail : 'Текущий план остался без изменений',
          })
        })
      return
    }

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
          travelMinutes: estimateMinutes(previous, ticket.coord, engineer.transport),
        }
        const next = stops[index]
        if (next) {
          stops[index] = {
            ...next,
            leg: straightLeg(ticket.coord, next.coord),
            transit: [],
            travelMinutes: estimateMinutes(ticket.coord, next.coord, engineer.transport),
            distanceKm: undefined,
          }
        }
        stops.splice(index, 0, added)
        // Обед остаётся между теми же заявками: вставка до него сдвигает его на одну
        const lunch =
          route.lunch && index < route.lunch.afterPosition
            ? { ...route.lunch, afterPosition: route.lunch.afterPosition + 1 }
            : route.lunch
        return { ...route, stops, lunch }
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

  /** «Перестроить маршрут»: другой транспорт у выбранного инженера — время участков и окончание из варианта. */
  const applyVariant = (engineerId: string, variant: RouteVariant) => {
    if (variant.current) return
    setRoutes((current) =>
      current.map((route) =>
        route.engineerId !== engineerId
          ? route
          : {
              ...route,
              stops: route.stops.map((stop, index) => ({
                ...stop,
                transit: [],
                travelMinutes: variant.legs[index]?.reduce((sum, step) => sum + step.minutes, 0) ?? stop.travelMinutes,
              })),
            },
      ),
    )
    setEngineers((current) =>
      current.map((item) =>
        item.id === engineerId ? { ...item, transport: variant.transport, routeTo: variant.endsAt || item.routeTo } : item,
      ),
    )
  }

  return {
    regionId,
    viewKey,
    hasPlan,
    /** Грузится версия плана — в том числе другая, пока на экране прежняя. */
    isLoading: query.isFetching,
    engineers,
    routes,
    unassigned,
    selectedId,
    selectedEngineer,
    selectedRoute,
    hoveredId,
    activeStopId,
    pendingDrop,
    isSavingDrop,
    select,
    hover: setHoveredId,
    toggleStop,
    requestDrop: (drop: PendingDrop | null) => {
      if (drop && options?.readOnly) {
        toast.danger('Этот план не меняется', {
          description: 'Старая версия или прошедший день — править можно последнюю версию текущего или будущего дня',
        })
        return
      }
      setPendingDrop(drop)
    },
    cancelDrop: () => setPendingDrop(null),
    confirmDrop,
    applyVariant,
  }
}

export type PlanMapBoard = ReturnType<typeof usePlanMapBoard>
