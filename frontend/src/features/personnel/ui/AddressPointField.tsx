import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { Map as MapLibreMap, Marker } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { createPortal } from 'react-dom'
import { RiMapPin2Fill, RiMapPinLine, RiZoomInLine, RiZoomOutLine } from '@remixicon/react'

import { MAP_DEFAULT_VIEW, OSM_STYLE } from '@/features/planning'
import { useLazyReverseGeocodeQuery } from '@/features/personnel/api'

import { errorReason } from '../lib/errors'

import { AddressField } from './AddressField'
import { Pin } from './BrigadeMap'
import { Hint } from './formParts'

export type AddressPoint = {
  address: string
  /** Точка [lng, lat] — из подсказки или с карты. */
  point: [number, number] | null
  /** Адрес с домом выбран из подсказок или найден по точке. Напечатанный — нет. */
  confirmed: boolean
}

export const EMPTY_ADDRESS_POINT: AddressPoint = { address: '', point: null, confirmed: false }

/** Пауза после остановки карты перед поиском адреса — пока тянут, не спрашиваем. */
const SETTLE_MS = 350
const PIN_FILL = 'var(--accent)'
const ZOOM_BUTTON =
  'flex size-8 cursor-pointer items-center justify-center text-foreground transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40'

type AddressPointFieldProps = {
  value: AddressPoint
  /** Сеттер состояния: адрес по точке приходит позже, поэтому обновления функциональные. */
  onChange: Dispatch<SetStateAction<AddressPoint>>
  label?: string
  /** Что ставят на карте, в винительном падеже: «заявку». */
  pointName?: string
  placeholder?: string
  /** Подсказка под полем, когда адрес выбран. */
  doneHint?: string
}

/**
 * Адрес с подсказками и картой — как у офиса бригады: печатаете и выбираете адрес с домом
 * или ставите точку на карте (двигается карта, булавка в центре), адрес находится по точке.
 */
export function AddressPointField({
  value,
  onChange,
  label,
  pointName = 'точку',
  placeholder = 'Улица и дом',
  doneHint = 'Точка на карте',
}: AddressPointFieldProps) {
  const [reverseGeocode] = useLazyReverseGeocodeQuery()
  const [picking, setPicking] = useState(false)
  const [locatingAt, setLocatingAt] = useState<string | null>(null)
  const [pickNote, setPickNote] = useState<string | null>(null)
  // Точка последнего поиска: ответы для прежних точек ничего не пишут
  const lastLocate = useRef<string | null>(null)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const stopLocating = () => {
    lastLocate.current = null
    setLocatingAt(null)
    setPickNote(null)
  }

  const locateAt = async (point: [number, number]) => {
    const key = point.join()
    lastLocate.current = key
    setPickNote(null)
    onChange((prev) => ({ ...prev, point, confirmed: false }))
    setLocatingAt(key)
    const current = () => alive.current && lastLocate.current === key
    try {
      const { address, hasHouse } = await reverseGeocode({ lat: point[1], lon: point[0] }).unwrap()
      if (!current()) return
      onChange((prev) =>
        prev.point?.join() === key && address ? { ...prev, address, confirmed: hasHouse } : prev,
      )
      if (!hasHouse) setPickNote('Здесь не нашёлся дом — поставьте булавку на здание')
    } catch (error) {
      if (current()) setPickNote(errorReason(error))
    } finally {
      if (alive.current) setLocatingAt((at) => (at === key ? null : at))
    }
  }

  const locating = locatingAt != null && value.point?.join() === locatingAt
  const hint =
    pickNote ??
    (locating
      ? 'Ищем адрес точки…'
      : picking
        ? 'Двигайте карту: адрес — под булавкой'
        : value.confirmed
          ? doneHint
          : 'Выберите адрес с номером дома из списка')

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-1">
        <AddressField
          value={value.address}
          confirmed={value.confirmed}
          busy={locating}
          label={label}
          pointName={pointName}
          placeholder={placeholder}
          onType={(address) => {
            stopLocating()
            setPicking(false)
            onChange((prev) => ({ ...prev, address, confirmed: false }))
          }}
          onPickOnMap={() => {
            setPickNote(null)
            setPicking(true)
          }}
          onSelect={(item) => {
            stopLocating()
            setPicking(false)
            onChange({ address: item.address, point: [item.lon, item.lat], confirmed: true })
          }}
        />
        <div className="flex items-start justify-between gap-2">
          <Hint>{hint}</Hint>
          <button
            type="button"
            aria-pressed={picking}
            onClick={() => {
              setPickNote(null)
              setPicking((next) => !next)
            }}
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 text-xs font-medium leading-5 text-link hover:underline"
          >
            <RiMapPinLine size={12} className="shrink-0" />
            {picking ? 'Готово' : 'Указать на карте'}
          </button>
        </div>
      </div>
      <PointMap
        point={value.point}
        picking={picking}
        onPick={() => {
          setPickNote(null)
          setPicking(true)
        }}
        onSettling={(settling) => {
          // Карту тянут — прежний адрес уже не про точку под булавкой
          if (settling) onChange((prev) => ({ ...prev, confirmed: false }))
        }}
        onCenter={(point) => void locateAt(point)}
      />
    </div>
  )
}

type PointMapProps = {
  point: [number, number] | null
  picking: boolean
  /** Клик по карте вне выбора — начать выбор с этого места. */
  onPick: () => void
  onSettling: (settling: boolean) => void
  onCenter: (point: [number, number]) => void
}

/** Небольшая карта под полем: точка адреса, а при выборе — булавка в центре. */
function PointMap({ point, picking, onPick, onSettling, onCenter }: PointMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  const [moving, setMoving] = useState(false)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const instance = new MapLibreMap({
      container,
      style: OSM_STYLE,
      center: point ?? MAP_DEFAULT_VIEW.center,
      zoom: point ? 15 : 9.5,
      minZoom: 7,
      maxZoom: 18,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: { compact: true },
    })
    instance.touchZoomRotate.disableRotation()
    // Окно открывается с анимацией — карта подстраивается под итоговый размер
    const observer = new ResizeObserver(() => instance.resize())
    observer.observe(container)
    setMap(instance)
    return () => {
      observer.disconnect()
      setMap(null)
      instance.remove()
    }
    // Карта создаётся один раз; точка доезжает эффектами ниже
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Маркер точки — вне выбора; при выборе точка — булавка в центре поверх карты
  const pointKey = point?.join() ?? ''
  useEffect(() => {
    if (!map || !point || picking) return
    const element = document.createElement('div')
    const marker = new Marker({ element, anchor: 'bottom' }).setLngLat(point).addTo(map)
    setSlot(element)
    return () => {
      marker.remove()
      setSlot(null)
    }
    // point меняется вместе с pointKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, pointKey, picking])

  // Выбрали адрес в подсказках — карта летит к нему. Во время выбора точку двигает сама карта
  const flown = useRef(pointKey)
  useEffect(() => {
    if (!map) return
    const changed = flown.current !== pointKey
    flown.current = pointKey
    if (picking || !changed || !point) return
    map.easeTo({ center: point, zoom: Math.max(map.getZoom(), 15), duration: 600 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, pointKey, picking])

  const handlers = useRef({ onPick, onSettling, onCenter, point })
  // Куда кликнули, начиная выбор: карта едет туда, когда подписка на движение уже есть
  const clickedAt = useRef<{ lng: number; lat: number } | null>(null)
  useEffect(() => {
    handlers.current = { onPick, onSettling, onCenter, point }
  })

  // Клик вне выбора — начать выбор с этого места
  useEffect(() => {
    if (!map || picking) return
    const click = (event: { lngLat: { lng: number; lat: number } }) => {
      clickedAt.current = event.lngLat
      handlers.current.onPick()
    }
    map.on('click', click)
    return () => {
      map.off('click', click)
    }
  }, [map, picking])

  useEffect(() => {
    if (!map || !picking) return
    const start = handlers.current.point
    const clicked = clickedAt.current
    clickedAt.current = null
    // jumpTo шлёт move-события сразу, до подписки ниже, — стартовая точка не «выбор»
    if (start && !clicked) map.jumpTo({ center: start, zoom: Math.max(map.getZoom(), 16) })
    let timer: ReturnType<typeof setTimeout> | undefined
    const moveStart = () => {
      clearTimeout(timer)
      setMoving(true)
      handlers.current.onSettling(true)
    }
    const moveEnd = () => {
      setMoving(false)
      clearTimeout(timer)
      timer = setTimeout(() => {
        const center = map.getCenter()
        handlers.current.onSettling(false)
        handlers.current.onCenter([center.lng, center.lat])
      }, SETTLE_MS)
    }
    const click = (event: { lngLat: { lng: number; lat: number } }) =>
      map.easeTo({ center: event.lngLat, duration: 300 })
    map.on('movestart', moveStart)
    map.on('moveend', moveEnd)
    map.on('click', click)
    if (clicked) map.easeTo({ center: clicked, zoom: Math.max(map.getZoom(), 16), duration: 300 })
    // Выбор без точки: то, что сейчас в центре, — уже выбор
    else if (!start) moveEnd()
    return () => {
      clearTimeout(timer)
      setMoving(false)
      map.off('movestart', moveStart)
      map.off('moveend', moveEnd)
      map.off('click', click)
    }
  }, [map, picking])

  const pin = (
    <Pin fill={PIN_FILL} title="">
      <RiMapPin2Fill size={16} className="text-[var(--beeline-white)]" />
    </Pin>
  )

  return (
    <div
      className="relative h-[180px] w-full shrink-0 overflow-hidden border border-border"
      style={{ borderRadius: 8 }}
    >
      {/* Стили MapLibre делают контейнер position: relative — размер ему даёт обёртка */}
      <div className="absolute inset-0">
        <div ref={containerRef} className="size-full" />
      </div>
      {slot ? createPortal(pin, slot) : null}

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
            {pin}
          </div>
        </div>
      ) : !point ? (
        <div
          className="absolute top-2 left-2 z-10 bg-surface px-2 py-1 text-xs leading-5 font-medium text-muted shadow-lg"
          style={{ borderRadius: 8 }}
        >
          Нажмите на карту, чтобы поставить точку
        </div>
      ) : null}

      <div
        className="absolute top-2 right-2 z-10 flex w-8 flex-col overflow-hidden bg-surface shadow-lg"
        style={{ borderRadius: 8 }}
      >
        <button
          type="button"
          aria-label="Приблизить"
          disabled={!map}
          onClick={() => map?.zoomIn()}
          className={ZOOM_BUTTON}
        >
          <RiZoomInLine size={14} />
        </button>
        <span aria-hidden className="mx-2 h-px bg-separator" />
        <button
          type="button"
          aria-label="Отдалить"
          disabled={!map}
          onClick={() => map?.zoomOut()}
          className={ZOOM_BUTTON}
        >
          <RiZoomOutLine size={14} />
        </button>
      </div>
    </div>
  )
}
