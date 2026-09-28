import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { LngLatBounds, Map as MapLibreMap, Marker } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { RiBuilding2Fill, RiZoomInLine, RiZoomOutLine } from '@remixicon/react'

import { MAP_DEFAULT_VIEW, OSM_STYLE, useGetPlanExportQuery } from '@/features/planning'
import type { PersonnelBrigade, PersonnelEngineer } from '@/features/personnel/types'
import { getInitials } from '@/shared/lib/text'
import { AppPanel } from '@/shared/ui'

import { engineerPositions } from '../lib/engineerPositions'

const ZOOM_BUTTON =
  'flex size-9 cursor-pointer items-center justify-center text-foreground transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'
/** Красный маркер офиса из макета; MapLibre-маркеры — DOM, но цвет задан литералом макета. */
const OFFICE_COLOR = '#EF4444'
const AVATAR_BG = '#EFEFF0'

/** Сегодня по Москве, YYYY-MM-DD — планы считаются в московском времени. */
function todayMoscow() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow' }).format(new Date())
}

function clock(now: number) {
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Europe/Moscow',
    hour: '2-digit',
    minute: '2-digit',
  }).format(now)
}

/** Булавка макета marker-point: белая с серым контуром, внутри — цветная капля. */
export function Pin({ fill, title, children }: { fill: string; title: string; children: ReactNode }) {
  return (
    <div title={title} className="relative cursor-default" style={{ width: 42, height: 48 }}>
      <svg
        width={42}
        height={48}
        viewBox="0 0 42 48"
        aria-hidden
        className="absolute inset-0 drop-shadow"
      >
        <path
          d="M21 47C21 47 1 33.5 1 21a20 20 0 0 1 40 0C41 33.5 21 47 21 47Z"
          fill="#FFFFFF"
          stroke="#C3C9D5"
        />
        <path d="M21 44C21 44 3 32 3 21a18 18 0 0 1 36 0C39 32 21 44 21 44Z" fill={fill} />
      </svg>
      <div
        className="absolute flex items-center justify-center"
        style={{ left: 5, top: 5, width: 32, height: 32 }}
      >
        {children}
      </div>
    </div>
  )
}

type MarkerItem = {
  key: string
  coord: [number, number]
  /** Сдвиг в пикселях — чтобы инженеры в одной точке не легли друг на друга. */
  offset: [number, number]
  content: ReactNode
}

/** Раскладывает совпадающие точки по кругу вокруг общей. */
function spread<T extends { coord: [number, number] }>(
  items: T[],
  office: [number, number] | null,
) {
  const groups = new Map<string, number[]>()
  const keyOf = (coord: [number, number]) => `${coord[0].toFixed(5)},${coord[1].toFixed(5)}`
  items.forEach((item, index) => {
    const key = keyOf(item.coord)
    groups.set(key, [...(groups.get(key) ?? []), index])
  })
  const officeKey = office ? keyOf(office) : null
  const offsets: [number, number][] = items.map(() => [0, 0])
  for (const [key, indexes] of groups) {
    // В офисе булавка офиса в центре — инженеры вокруг неё
    const atOffice = key === officeKey
    if (indexes.length === 1 && !atOffice) continue
    const radius = atOffice ? 40 : 24
    indexes.forEach((itemIndex, position) => {
      const angle = (2 * Math.PI * position) / indexes.length - Math.PI / 2
      offsets[itemIndex] = [
        Math.round(radius * Math.cos(angle)),
        Math.round(radius * Math.sin(angle)),
      ]
    })
  }
  return offsets
}

type BrigadeMapProps = {
  brigade: PersonnelBrigade
  engineers: PersonnelEngineer[]
  /** Где рисовать офис: сохранённая точка или выбранная до сохранения. */
  officePoint: [number, number] | null
  /** Подпись офиса в подсказке булавки — адрес из формы, в том числе ещё не сохранённый. */
  officeLabel?: string
  /**
   * Выбор точки офиса, как на сайтах доставки: булавка стоит в центре, двигается карта.
   * Остановилась — onCenter с точкой под булавкой.
   */
  picking?: boolean
  onCenter?: (point: [number, number]) => void
  /** Карта едет или только встала — точка под булавкой ещё не выбрана. */
  onSettling?: (settling: boolean) => void
  /** Enter или Esc — выбор закончен. */
  onDone?: () => void
}

/** Пауза после остановки карты перед поиском адреса — пока тянут, не спрашиваем. */
const SETTLE_MS = 350

/**
 * Офис бригады и её инженеры на карте. Живых координат нет — инженеры стоят там,
 * где они сейчас по сегодняшнему плану региона; нет плана — только офис.
 */
export function BrigadeMap({
  brigade,
  engineers,
  officePoint,
  officeLabel,
  picking = false,
  onCenter,
  onSettling,
  onDone,
}: BrigadeMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [slots, setSlots] = useState<Map<string, HTMLElement>>(() => new Map())
  const [moving, setMoving] = useState(false)

  const today = todayMoscow()
  const { currentData: plan, isFetching } = useGetPlanExportQuery({
    regionId: brigade.regionId,
    date: today,
  })
  // Положение по расписанию сдвигается со временем — пересчитываем раз в минуту
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(timer)
  }, [])

  const office = officePoint
  const items = useMemo<MarkerItem[]>(() => {
    const byId = new Map(engineers.map((engineer) => [engineer.id, engineer]))
    const positions =
      plan && office
        ? engineerPositions(plan, office, now).filter((position) => byId.has(position.engineerId))
        : []
    const offsets = spread(positions, office)
    const people: MarkerItem[] = positions.map((position, index) => {
      const engineer = byId.get(position.engineerId)!
      return {
        key: `engineer-${engineer.id}`,
        coord: position.coord,
        offset: offsets[index]!,
        content: (
          <Pin fill={AVATAR_BG} title={`${engineer.name} — ${position.status.toLowerCase()}`}>
            <span className="flex size-8 items-center justify-center rounded-full bg-surface-tertiary text-xs leading-5 font-medium text-foreground">
              {getInitials(engineer.name.replace(/^Бригада\s+/, ''))}
            </span>
          </Pin>
        ),
      }
    })
    const officeItem: MarkerItem[] = office
      ? [
          {
            key: 'office',
            coord: office,
            offset: [0, 0],
            content: (
              <Pin fill={OFFICE_COLOR} title={`Офис: ${officeLabel ?? brigade.officeAddress ?? ''}`}>
                <RiBuilding2Fill size={16} className="text-[var(--beeline-white)]" />
              </Pin>
            ),
          },
        ]
      : []
    return [...people, ...officeItem]
  }, [plan, office, now, engineers, officeLabel, brigade.officeAddress])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const instance = new MapLibreMap({
      container,
      style: OSM_STYLE,
      center: office ?? MAP_DEFAULT_VIEW.center,
      zoom: MAP_DEFAULT_VIEW.zoom,
      minZoom: 8,
      maxZoom: 18,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: { compact: true },
    })
    instance.touchZoomRotate.disableRotation()
    setMap(instance)
    return () => {
      setMap(null)
      instance.remove()
    }
    // Карта создаётся один раз; офис и инженеры доезжают эффектами ниже
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // При выборе офис — булавка в центре поверх карты, маркер офиса не нужен
  const shown = useMemo(
    () => (picking ? items.filter((item) => item.key !== 'office') : items),
    [items, picking],
  )

  // Маркеры — DOM-элементы MapLibre, содержимое рисует React через портал
  useEffect(() => {
    if (!map) return
    const next = new Map<string, HTMLElement>()
    const markers = shown.map((item) => {
      const element = document.createElement('div')
      next.set(item.key, element)
      return new Marker({ element, anchor: 'bottom', offset: item.offset })
        .setLngLat(item.coord)
        .addTo(map)
    })
    setSlots(next)
    return () => markers.forEach((marker) => marker.remove())
  }, [map, shown])

  // Выбор точки: карта встаёт центром на офис, дальше двигают её; клик — «подвинь сюда»
  const pickRef = useRef({ onCenter, onDone, onSettling, officePoint })
  useEffect(() => {
    pickRef.current = { onCenter, onDone, onSettling, officePoint }
  })
  useEffect(() => {
    if (!map || !picking) return
    const start = pickRef.current.officePoint
    // jumpTo шлёт move-события сразу, до подписки ниже, — стартовая точка не «выбор»
    if (start) map.jumpTo({ center: start, zoom: Math.max(map.getZoom(), 16) })
    let timer: ReturnType<typeof setTimeout> | undefined
    const moveStart = () => {
      clearTimeout(timer)
      setMoving(true)
      pickRef.current.onSettling?.(true)
    }
    const moveEnd = () => {
      setMoving(false)
      clearTimeout(timer)
      timer = setTimeout(() => {
        const center = map.getCenter()
        pickRef.current.onSettling?.(false)
        pickRef.current.onCenter?.([center.lng, center.lat])
      }, SETTLE_MS)
    }
    const click = (event: { lngLat: { lng: number; lat: number } }) =>
      map.easeTo({ center: event.lngLat, duration: 300 })
    const key = (event: KeyboardEvent) => {
      // Enter в поле формы — не «готово»: человек печатает
      const target = event.target as HTMLElement | null
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (event.key === 'Escape' || event.key === 'Enter') pickRef.current.onDone?.()
    }
    map.on('movestart', moveStart)
    map.on('moveend', moveEnd)
    map.on('click', click)
    window.addEventListener('keydown', key)
    return () => {
      clearTimeout(timer)
      setMoving(false)
      pickRef.current.onSettling?.(false)
      map.off('movestart', moveStart)
      map.off('moveend', moveEnd)
      map.off('click', click)
      window.removeEventListener('keydown', key)
    }
  }, [map, picking])

  // Выбрали адрес в подсказках — карта летит к нему. Во время выбора точку двигает сама карта
  const draftKey = officePoint?.join() ?? ''
  const flown = useRef(draftKey)
  useEffect(() => {
    if (!map) return
    if (picking || flown.current === draftKey) {
      flown.current = draftKey
      return
    }
    flown.current = draftKey
    if (officePoint) {
      map.easeTo({ center: officePoint, zoom: Math.max(map.getZoom(), 15), duration: 600 })
    }
    // officePoint меняется вместе с draftKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, draftKey, picking])

  // Камера: офис и все инженеры; переезд сохранённого офиса или смена бригады — заново.
  // Точку, поставленную кликом, не догоняем: её и так видно
  const officeKey = brigade.officePoint ? brigade.officePoint.join(',') : ''
  const positioned = items.length
  useEffect(() => {
    if (!map) return
    const coords = items.map((item) => item.coord)
    if (coords.length === 0) return
    const bounds = coords.reduce(
      (acc, coord) => acc.extend(coord),
      new LngLatBounds(coords[0], coords[0]),
    )
    map.fitBounds(bounds, { padding: 80, duration: 0, maxZoom: 14 })
    // Камера не прыгает каждую минуту вслед за инженерами
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, brigade.id, officeKey, positioned])

  const note = picking
    ? 'Двигайте карту — офис под булавкой. Enter или Esc — готово'
    : !office
      ? 'У бригады не указан офис'
      : isFetching && !plan
        ? null
        : plan
          ? `Инженеры — где они по плану на ${clock(now)}`
          : 'На сегодня плана нет — показан только офис'

  return (
    <AppPanel className="relative min-h-0 flex-1 overflow-hidden">
      <div className="absolute inset-0">
        <div ref={containerRef} className="size-full" />
      </div>

      {shown.map((item) => {
        const slot = slots.get(item.key)
        return slot ? createPortal(item.content, slot, item.key) : null
      })}

      {picking ? (
        // Кончик булавки — ровно в центре карты; пока карту тянут, булавка приподнята
        <div aria-hidden className="pointer-events-none absolute top-1/2 left-1/2 z-10">
          <span
            className="absolute rounded-full bg-black/25"
            style={{ width: 12, height: 4, left: -6, top: -2 }}
          />
          <div
            className="absolute transition-transform duration-150"
            style={{ left: -21, top: -48, transform: `translateY(${moving ? -10 : 0}px)` }}
          >
            <Pin fill={OFFICE_COLOR} title="">
              <RiBuilding2Fill size={16} className="text-[var(--beeline-white)]" />
            </Pin>
          </div>
        </div>
      ) : null}

      {note ? (
        <div
          className="absolute top-3 left-3 z-10 bg-surface px-3 py-1.5 text-xs leading-5 font-medium text-muted shadow-lg"
          style={{ borderRadius: 8 }}
        >
          {note}
        </div>
      ) : null}

      <div
        className="absolute top-1/2 right-[10px] z-10 flex w-9 -translate-y-1/2 flex-col overflow-hidden bg-surface shadow-lg"
        style={{ borderRadius: 8 }}
      >
        <button
          type="button"
          aria-label="Приблизить"
          disabled={!map}
          onClick={() => map?.zoomIn()}
          className={ZOOM_BUTTON}
        >
          <RiZoomInLine size={16} />
        </button>
        <span aria-hidden className="mx-2 h-px bg-separator" />
        <button
          type="button"
          aria-label="Отдалить"
          disabled={!map}
          onClick={() => map?.zoomOut()}
          className={ZOOM_BUTTON}
        >
          <RiZoomOutLine size={16} />
        </button>
      </div>
    </AppPanel>
  )
}
