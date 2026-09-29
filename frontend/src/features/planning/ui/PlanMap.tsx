import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  setWorkerUrl,
  type ExpressionSpecification,
  type GeoJSONSource,
  type MapOptions,
} from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import { RiZoomInLine, RiZoomOutLine } from '@remixicon/react'
import type { Feature, FeatureCollection, LineString, MultiLineString } from 'geojson'

import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import { routeCoordinates } from '../lib/routeGeometry'
import type { EngineerRoute, LngLat, MapEngineer } from '../mapTypes'
import { MAP_DEFAULT_VIEW } from '../mocks'

// MapLibre ищет воркер рядом со своим файлом, а после бандлинга его там нет —
// отдаём URL воркера, собранного Vite отдельным чанком.
setWorkerUrl(maplibreWorkerUrl)

// Растровые тайлы OSM — та же подложка, что во фрейме макета, ключ не нужен.
export const OSM_STYLE: MapOptions['style'] = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
}

const LINE_ROUND = { 'line-join': 'round', 'line-cap': 'round' } as const
const LINE_DASHED = { 'line-join': 'round', 'line-cap': 'butt' } as const
/** MapLibre paint не понимает CSS variables, поэтому здесь литералы Beeline primitives. */
const STRAIGHT_COLOR = '#77849D'
const STRAIGHT_END = '#64748b'
const ACTIVE_STOP = '#F84A00'
const OVERVIEW_LAYERS = ['overview-road', 'overview-straight']
/** Насколько бледнеют чужие маршруты и их точки, пока курсор на одном из маршрутов. */
const DIM_OPACITY = 0.5

type LineFeature = Feature<LineString | MultiLineString>

const collection = (features: LineFeature[]): FeatureCollection => ({
  type: 'FeatureCollection',
  features,
})

function addLayers(map: MapLibreMap) {
  map.addSource('overview', { type: 'geojson', data: collection([]) })
  map.addSource('selected', { type: 'geojson', data: collection([]) })

  map.addLayer({
    id: 'overview-road',
    type: 'line',
    source: 'overview',
    filter: ['!', ['get', 'straight']],
    layout: LINE_ROUND,
    paint: { 'line-color': ['get', 'color'], 'line-width': 6 },
  })
  map.addLayer({
    id: 'overview-straight',
    type: 'line',
    source: 'overview',
    filter: ['get', 'straight'],
    layout: LINE_DASHED,
    paint: { 'line-color': STRAIGHT_COLOR, 'line-width': 4, 'line-dasharray': [1, 2] },
  })

  // Выбранный маршрут по макету: серый контур, белая подложка и линия поверх.
  map.addLayer({
    id: 'selected-casing',
    type: 'line',
    source: 'selected',
    layout: LINE_ROUND,
    paint: { 'line-color': '#C3C9D5', 'line-width': ['case', ['get', 'straight'], 10, 12] },
  })
  map.addLayer({
    id: 'selected-underlay',
    type: 'line',
    source: 'selected',
    layout: LINE_ROUND,
    paint: { 'line-color': '#ffffff', 'line-width': ['case', ['get', 'straight'], 8, 10] },
  })
  map.addLayer({
    id: 'selected-road',
    type: 'line',
    source: 'selected',
    filter: ['!', ['get', 'straight']],
    layout: LINE_ROUND,
    paint: { 'line-color': ['get', 'color'], 'line-width': 6 },
  })
  map.addLayer({
    id: 'selected-straight',
    type: 'line',
    source: 'selected',
    filter: ['get', 'straight'],
    layout: LINE_DASHED,
    paint: { 'line-color': STRAIGHT_COLOR, 'line-width': 6, 'line-dasharray': [1, 2] },
  })
}

/** Участки маршрутов фичами: сплошные по улицам отдельно от прямых. Дорога к обеду — тоже. */
function legFeatures(route: EngineerRoute, properties: Record<string, unknown>): LineFeature[] {
  const legs = [...route.stops.map((stop) => stop.leg), ...(route.lunch?.leg ? [route.lunch.leg] : [])]
  const byKind = (straight: boolean) =>
    legs.filter((leg) => leg.straight === straight && leg.line.length > 1)
  return [false, true].flatMap((straight) => {
    const lines = byKind(straight)
    if (lines.length === 0) return []
    return [
      {
        type: 'Feature' as const,
        properties: { ...properties, straight },
        geometry: {
          type: 'MultiLineString' as const,
          coordinates: lines.map((leg) => leg.line),
        },
      },
    ]
  })
}

function setData(map: MapLibreMap, source: string, features: LineFeature[]) {
  ;(map.getSource(source) as GeoJSONSource | undefined)?.setData(collection(features))
}

// ── Маркеры ────────────────────────────────────────────────────────────────

function pointElement(options: {
  color: string
  label?: string
  variant: 'count' | 'ring' | 'dot'
  dim?: boolean
  title?: string
  onClick?: () => void
}) {
  const root = document.createElement(options.onClick ? 'button' : 'div')
  if (root instanceof HTMLButtonElement) root.type = 'button'
  if (options.title) root.title = options.title
  root.style.cssText = `width:20px;height:20px;border-radius:9999px;background:var(--surface);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;padding:0;cursor:${options.onClick ? 'pointer' : 'default'};transition:filter .15s`
  // Marker сам пишет opacity в style элемента, поэтому бледнеем через filter.
  if (options.dim) root.style.filter = `opacity(${DIM_OPACITY})`
  const inner = document.createElement('span')
  const size = options.variant === 'count' ? 14 : 8
  const background = options.variant === 'ring' ? 'var(--surface)' : options.color
  const border = options.variant === 'count' ? 0 : 3
  inner.style.cssText = `box-sizing:border-box;width:${size}px;height:${size}px;border-radius:9999px;background:${background};border:${border}px solid ${options.color};display:flex;align-items:center;justify-content:center;color:#FFFFFF;font:600 10px/1 Inter,system-ui,sans-serif`
  if (options.label) inner.textContent = options.label
  root.append(inner)
  if (options.onClick) {
    root.addEventListener('click', (event) => {
      event.stopPropagation()
      options.onClick?.()
    })
  }
  return root
}

/** Место обеда: чашка в кружке цвета маршрута. */
function lunchElement(color: string, title: string, dim = false) {
  const root = document.createElement('div')
  root.title = title
  root.style.cssText = `width:20px;height:20px;border-radius:9999px;background:var(--surface);border:1px solid var(--border);display:flex;align-items:center;justify-content:center`
  if (dim) root.style.filter = `opacity(${DIM_OPACITY})`
  const inner = document.createElement('span')
  inner.style.cssText = `width:14px;height:14px;border-radius:9999px;background:${color};display:flex;align-items:center;justify-content:center`
  inner.innerHTML =
    '<svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9h12v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M16 11h1.5a2.5 2.5 0 0 1 0 5H16"/></svg>'
  root.append(inner)
  return root
}

/** Квадратный номер как в списке маршрута — отмечает раскрытую заявку. */
function activeStopElement(label: string) {
  const root = document.createElement('div')
  root.style.cssText =
    'width:24px;height:24px;border-radius:8px;background:var(--surface);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;box-shadow:0 10px 15px -3px rgb(0 0 0/.1),0 4px 6px -4px rgb(0 0 0/.1)'
  const inner = document.createElement('span')
  inner.style.cssText = `width:18px;height:18px;border-radius:5px;background:${ACTIVE_STOP};color:#FFFFFF;display:flex;align-items:center;justify-content:center;font:600 14px/20px Inter,system-ui,sans-serif`
  inner.textContent = label
  root.append(inner)
  return root
}

// ── Компонент ──────────────────────────────────────────────────────────────

const ZOOM_BUTTON =
  'flex size-9 cursor-pointer items-center justify-center text-foreground transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'

type PlanMapProps = {
  className?: string
  engineers: MapEngineer[]
  routes: EngineerRoute[]
  selectedId: string | null
  hoveredId: string | null
  activeStopId: string | null
  /** Ширина панели поверх карты слева — чтобы маршрут не прятался под ней. */
  overlayInset?: number
  /** Смена ключа (например, региона) заново подгоняет камеру под все маршруты. */
  viewKey?: string | number | null
  onHoverEngineer?: (engineerId: string | null) => void
  onSelectEngineer?: (engineerId: string) => void
  onSelectStop?: (stopId: string) => void
  /** Панели поверх карты, например маршрут выбранного инженера. */
  children?: ReactNode
}

export function PlanMap({
  className,
  engineers,
  routes,
  selectedId,
  hoveredId,
  activeStopId,
  overlayInset = 0,
  viewKey,
  onHoverEngineer,
  onSelectEngineer,
  onSelectStop,
  children,
}: PlanMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)
  const [ready, setReady] = useState(false)
  const markersRef = useRef<Marker[]>([])
  // Колбэки меняются каждый рендер — слушатели карты читают свежие через ref.
  const handlersRef = useRef({ onHoverEngineer, onSelectEngineer, onSelectStop })
  useEffect(() => {
    handlersRef.current = { onHoverEngineer, onSelectEngineer, onSelectStop }
  })

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const instance = new MapLibreMap({
      container,
      style: OSM_STYLE,
      center: MAP_DEFAULT_VIEW.center,
      zoom: MAP_DEFAULT_VIEW.zoom,
      minZoom: 8,
      maxZoom: 18,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: { compact: true },
    })
    instance.touchZoomRotate.disableRotation()

    instance.on('load', () => {
      addLayers(instance)
      const engineerAt = (event: { features?: { properties: Record<string, unknown> }[] }) => {
        const id = event.features?.[0]?.properties.engineerId
        return typeof id === 'string' ? id : null
      }
      instance.on('mousemove', OVERVIEW_LAYERS, (event) => {
        instance.getCanvas().style.cursor = 'pointer'
        handlersRef.current.onHoverEngineer?.(engineerAt(event))
      })
      instance.on('mouseleave', OVERVIEW_LAYERS, () => {
        instance.getCanvas().style.cursor = ''
        handlersRef.current.onHoverEngineer?.(null)
      })
      instance.on('click', OVERVIEW_LAYERS, (event) => {
        const id = engineerAt(event)
        if (id) handlersRef.current.onSelectEngineer?.(id)
      })
      setReady(true)
    })
    setMap(instance)

    return () => {
      markersRef.current.forEach((marker) => marker.remove())
      markersRef.current = []
      setReady(false)
      setMap(null)
      instance.remove()
    }
  }, [])

  // Линии: в обзоре — все маршруты, при выборе — только выбранный с разбивкой на отрезки.
  useEffect(() => {
    if (!map || !ready) return
    const colorOf = new Map(engineers.map((engineer) => [engineer.id, engineer.color]))

    setData(
      map,
      'overview',
      selectedId != null
        ? []
        : routes.flatMap((route) =>
            legFeatures(route, { engineerId: route.engineerId, color: colorOf.get(route.engineerId) }),
          ),
    )

    const selected = routes.find((route) => route.engineerId === selectedId)
    setData(
      map,
      'selected',
      selected ? legFeatures(selected, { color: colorOf.get(selected.engineerId) }) : [],
    )
  }, [map, ready, engineers, routes, selectedId])

  // Подсветка маршрута под курсором: остальные бледнеют и тоньшают, а он рисуется поверх них.
  useEffect(() => {
    if (!map || !ready) return
    const hovered: ExpressionSpecification = ['==', ['get', 'engineerId'], hoveredId ?? '']
    const pick = (on: number, off: number): number | ExpressionSpecification =>
      hoveredId == null ? on : ['case', hovered, on, off]
    for (const layer of OVERVIEW_LAYERS) {
      map.setPaintProperty(layer, 'line-opacity', pick(1, DIM_OPACITY))
      map.setLayoutProperty(layer, 'line-sort-key', pick(1, 0))
    }
    map.setPaintProperty('overview-road', 'line-width', pick(6, 4))
    map.setPaintProperty('overview-straight', 'line-width', pick(4, 4 / 1.5))
  }, [map, ready, hoveredId])

  // Точки маршрутов.
  useEffect(() => {
    if (!map || !ready) return
    markersRef.current.forEach((marker) => marker.remove())
    const markers: Marker[] = []
    const add = (element: HTMLElement, coord: LngLat) =>
      markers.push(new Marker({ element }).setLngLat(coord).addTo(map))

    if (selectedId == null) {
      for (const engineer of engineers) {
        const route = routes.find((item) => item.engineerId === engineer.id)
        if (!route || route.stops.length === 0) continue
        const dim = hoveredId != null && hoveredId !== engineer.id
        const select = () => handlersRef.current.onSelectEngineer?.(engineer.id)
        route.stops.forEach((stop, index) =>
          add(
            pointElement({
              color: engineer.color,
              label: String(index + 1),
              variant: 'count',
              dim,
              title: `${engineer.name} · №${stop.id}`,
              onClick: select,
            }),
            stop.coord,
          ),
        )
        // Место обеда — там, куда на обед едут; у последней заявки оно совпадает с ней
        if (route.lunch?.leg) {
          add(
            lunchElement(engineer.color, `${engineer.name} · обед ${route.lunch.from}–${route.lunch.to}`, dim),
            route.lunch.coord,
          )
        }
      }
      // Старт у бригад общий — одна точка «A» поверх остальных.
      const starts = new Map(engineers.map((engineer) => [engineer.start.coord.join(','), engineer]))
      for (const engineer of starts.values()) {
        add(pointElement({ color: '#28303F', label: 'A', variant: 'count', title: engineer.start.address }), engineer.start.coord)
      }
    } else {
      const engineer = engineers.find((item) => item.id === selectedId)
      const route = routes.find((item) => item.engineerId === selectedId)
      if (engineer && route) {
        // Без раскрытой заявки номера у всех точек; с раскрытой — только у неё и предыдущей,
        // чтобы было видно, откуда куда ехать. Перед первой заявкой — старт «A».
        const active = route.stops.findIndex((stop) => stop.id === activeStopId)
        const numbered = (index: number) => active < 0 || index === active - 1
        add(
          numbered(-1)
            ? pointElement({ color: '#28303F', label: 'A', variant: 'count', title: engineer.start.address })
            : pointElement({ color: engineer.color, variant: 'ring', title: engineer.start.address }),
          engineer.start.coord,
        )
        route.stops.forEach((stop, index) => {
          if (index === active) return
          // В заявку ведёт прямая — точка серая, как конец пунктира в макете.
          add(
            pointElement({
              color: stop.leg.straight ? STRAIGHT_END : engineer.color,
              label: numbered(index) ? String(index + 1) : undefined,
              variant: numbered(index) ? 'count' : 'dot',
              title: `${index + 1}. ${stop.address}`,
              onClick: () => handlersRef.current.onSelectStop?.(stop.id),
            }),
            stop.coord,
          )
        })
        if (route.lunch?.leg) {
          add(
            lunchElement(engineer.color, `Обед ${route.lunch.from}–${route.lunch.to} · ${route.lunch.place}`),
            route.lunch.coord,
          )
        }
        // Раскрытая заявка последней — поверх соседних точек.
        if (active >= 0) add(activeStopElement(String(active + 1)), route.stops[active].coord)
      }
    }
    markersRef.current = markers
  }, [map, ready, engineers, routes, selectedId, hoveredId, activeStopId])

  // Камера: выбранный маршрут целиком справа от панели, без выбора — все маршруты.
  useEffect(() => {
    if (!map || !ready) return
    const coords =
      selectedId == null
        ? engineers.flatMap((engineer) =>
            routeCoordinates(engineer, routes.find((route) => route.engineerId === engineer.id)),
          )
        : routeCoordinates(
            engineers.find((engineer) => engineer.id === selectedId)!,
            routes.find((route) => route.engineerId === selectedId),
          )
    if (coords.length === 0) return
    // При выборе снизу появляется лента заявок и карта сжимается — меряем её заново до подгонки.
    map.resize()
    const bounds = coords.reduce(
      (acc, coord) => acc.extend(coord),
      new LngLatBounds(coords[0], coords[0]),
    )
    map.fitBounds(bounds, {
      padding: { top: 48, bottom: 48, left: overlayInset + 48, right: 72 },
      duration: selectedId == null ? 0 : 600,
      maxZoom: 15,
    })
    // Камера двигается только при смене выбора или региона, а не при каждой правке маршрута.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, ready, selectedId, viewKey])

  return (
    <AppPanel className={cn('relative min-h-0 flex-1 overflow-hidden', className)}>
      {/* maplibregl-map ставит контейнеру position: relative, поэтому растягиваем обёртку. */}
      <div className="absolute inset-0">
        <div ref={containerRef} className="size-full" />
      </div>

      {children}

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
