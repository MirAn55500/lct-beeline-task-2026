import { Fragment, type ReactNode, type Ref } from 'react'
import {
  RiArrowDownSLine,
  RiArrowRightSFill,
  RiArrowRightUpLine,
  RiArrowUpSLine,
  RiBuilding2Fill,
  RiMapPinAddLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

import { legSteps } from '../../lib/routeSteps'
import type { EngineerRoute, MapEngineer } from '../../mapTypes'
import { MetaSeparator, TicketTags } from './parts'
import { RouteStepChip } from './RouteSteps'

/** Ширина колонки панели поверх карты вместе с отступами — для fitBounds. */
export const ROUTE_PANEL_INSET = 333

const ACTIVE = '#ff383c'

function StopMarker({ children, active }: { children: ReactNode; active: boolean }) {
  return (
    <span
      className="flex size-6 shrink-0 items-center justify-center border border-[#dedee0] bg-white"
      style={{ borderRadius: 8, margin: -2 }}
    >
      <span
        className="flex size-[18px] items-center justify-center text-sm leading-5 font-semibold text-white"
        style={{ borderRadius: 5, background: active ? ACTIVE : '#18181b' }}
      >
        {children}
      </span>
    </span>
  )
}

/** Синяя линия с точкой — куда встанет перетаскиваемая заявка. */
function DropIndicator({ edge }: { edge: 'top' | 'bottom' }) {
  return (
    <span
      aria-hidden
      className={cn(
        'pointer-events-none absolute right-0 left-0 z-10 h-0.5 bg-[#0485f7]',
        edge === 'top' ? '-top-px' : '-bottom-px',
      )}
    >
      <span className="absolute top-1/2 right-0 size-2.5 -translate-y-1/2 rounded-full bg-[#0485f7]" />
    </span>
  )
}

type RouteDetailsPanelProps = {
  engineer: MapEngineer
  route: EngineerRoute
  activeStopId: string | null
  onToggleStop: (stopId: string) => void
  onAddTicket: () => void
  /** «Изменить параметры маршрута» — окно с транспортом и вариантами маршрута. */
  onEditParams: () => void
  /** Позиция вставки при перетаскивании заявки, null — не тащат. */
  dropIndex: number | null
  /** Список для хит-теста перетаскивания: элементы с data-stop-index. */
  listRef?: Ref<HTMLDivElement>
}

export function RouteDetailsPanel({
  engineer,
  route,
  activeStopId,
  onToggleStop,
  onAddTicket,
  onEditParams,
  dropIndex,
  listRef,
}: RouteDetailsPanelProps) {
  const stops = route.stops

  return (
    <div
      className="absolute top-0 bottom-0 left-0 z-10 flex p-3"
      style={{ width: ROUTE_PANEL_INSET }}
    >
      <div
        className="flex min-h-0 min-w-0 flex-1 flex-col bg-white shadow-lg"
        style={{ borderRadius: 8 }}
      >
        <div className="flex shrink-0 flex-col gap-1 px-3 pt-3 pb-2">
          <h2 className="text-base leading-6 font-semibold text-[#18181b]">
            Маршрут{' '}
            <span className="text-[#71717a]">
              с {engineer.routeFrom} по {engineer.routeTo}
            </span>
          </h2>
          <button
            type="button"
            onClick={onEditParams}
            className="inline-flex w-fit cursor-pointer items-start gap-0.5 text-sm leading-5 font-medium text-[#18181b] hover:underline"
          >
            Изменить параметры маршрута
            <RiArrowRightUpLine size={10} className="mt-0.5 opacity-60" />
          </button>
        </div>

        <div
          ref={listRef}
          className="relative flex min-h-0 flex-1 flex-col overflow-y-auto"
        >
          <div className="relative flex items-center gap-2 border-b border-[#dedee0] p-3">
            <span
              className="flex size-6 shrink-0 items-center justify-center border border-[#dedee0] bg-white"
              style={{ borderRadius: 8, margin: -2 }}
            >
              <span
                className="flex size-[18px] items-center justify-center"
                style={{ borderRadius: 5, background: ACTIVE }}
              >
                <RiBuilding2Fill size={12} className="text-white" />
              </span>
            </span>
            <span className="min-w-0 flex-1 truncate text-sm leading-5 font-medium text-[#18181b]">
              {engineer.start.address}
            </span>
            {dropIndex === 0 && stops.length === 0 ? <DropIndicator edge="bottom" /> : null}
          </div>

          {stops.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm leading-5 text-[#71717a]">
              В маршруте пока нет заявок
            </p>
          ) : null}

          {stops.map((stop, index) => {
            const expanded = stop.id === activeStopId
            const Chevron = expanded ? RiArrowUpSLine : RiArrowDownSLine
            return (
              <div
                key={stop.id}
                data-stop-index={index}
                className="relative border-b border-[#dedee0]"
              >
                {dropIndex === index ? <DropIndicator edge="top" /> : null}
                {dropIndex === stops.length && index === stops.length - 1 ? (
                  <DropIndicator edge="bottom" />
                ) : null}
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => onToggleStop(stop.id)}
                  className="flex w-full cursor-pointer flex-col gap-2 p-3 text-left outline-none transition-colors hover:bg-[#fafafa] focus-visible:bg-[#fafafa]"
                >
                  <span className="flex flex-col gap-1">
                    <span className="flex items-center gap-2">
                      <StopMarker active={expanded}>{index + 1}</StopMarker>
                      <span className="min-w-0 flex-1 truncate text-sm leading-5 font-medium text-[#18181b]">
                        {stop.address}
                      </span>
                    </span>
                    <span className="flex items-center gap-2 text-sm leading-5 font-medium text-[#71717a]">
                      <span>№{stop.id}</span>
                      <MetaSeparator />
                      <span className="min-w-0 flex-1 truncate">{stop.typeLabel}</span>
                      <Chevron size={16} className="shrink-0" />
                    </span>
                  </span>
                  {expanded ? (
                    <span className="flex flex-col gap-2">
                      <TicketTags ticket={stop} />
                      <span
                        className="flex flex-wrap items-center gap-1"
                        title={stop.transit.join('\n') || undefined}
                      >
                        {legSteps(stop.transit, engineer.transport, stop.travelMinutes).map((step, stepIndex) => (
                          <Fragment key={stepIndex}>
                            {stepIndex > 0 ? (
                              <RiArrowRightSFill size={14} aria-hidden className="shrink-0 text-[#71717a]" />
                            ) : null}
                            <RouteStepChip step={step} />
                          </Fragment>
                        ))}
                      </span>
                    </span>
                  ) : null}
                </button>
              </div>
            )
          })}
        </div>

        <div className="shrink-0 px-3 pt-2 pb-3">
          <button
            type="button"
            onClick={onAddTicket}
            className="flex h-9 w-full cursor-pointer items-center justify-center gap-2 px-4 text-sm leading-5 font-medium text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
            style={{ borderRadius: 8 }}
          >
            <RiMapPinAddLine size={16} />
            Добавить заявку
          </button>
        </div>
      </div>
    </div>
  )
}
