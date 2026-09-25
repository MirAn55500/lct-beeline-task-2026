import { useState } from 'react'
import {
  RiBikeLine,
  RiBus2Fill,
  RiBus2Line,
  RiCarFill,
  RiCarLine,
  RiErrorWarningLine,
  RiRidingFill,
  RiWalkFill,
  RiWalkLine,
} from '@remixicon/react'
import { toast } from '@heroui/react'

import { cn } from '@/shared/lib/cn'
import { AppModal, buttonClass } from '@/shared/ui'

import { formatDuration } from '../../lib/routeSteps'
import { ROUTE_TRANSPORTS, routeVariants, type RouteVariant } from '../../lib/routeVariants'
import type { EngineerRoute, MapEngineer, MapTransport } from '../../mapTypes'
import { RouteStepsChain } from './RouteSteps'

const CHIPS: Record<MapTransport, { label: string; icon: typeof RiCarLine; activeIcon: typeof RiCarLine }> = {
  car: { label: 'Автомобиль', icon: RiCarLine, activeIcon: RiCarFill },
  public: { label: 'Общ. транспорт', icon: RiBus2Line, activeIcon: RiBus2Fill },
  bike: { label: 'Велосипед', icon: RiBikeLine, activeIcon: RiRidingFill },
  walking: { label: 'Пешеход', icon: RiWalkLine, activeIcon: RiWalkFill },
}

type RouteParamsDialogProps = {
  isOpen: boolean
  engineer: MapEngineer
  route: EngineerRoute
  onClose: () => void
  onApply: (variant: RouteVariant) => void
}

/**
 * «Параметры маршрута»: транспорт, на котором инженер может ехать, и варианты маршрута по нему.
 * Выбор варианта спрашивает «Перестроить маршрут?» — время прибытия на следующие заявки поменяется.
 */
export function RouteParamsDialog({ isOpen, engineer, route, onClose, onApply }: RouteParamsDialogProps) {
  // Как в макете: у общественного транспорта сразу включена и ходьба.
  const [transports, setTransports] = useState<MapTransport[]>(() =>
    engineer.transport === 'public' ? ['public', 'walking'] : [engineer.transport],
  )
  const [pending, setPending] = useState<RouteVariant | null>(null)
  const variants = routeVariants(engineer, route, transports)
  const addresses = route.stops.map((stop) => stop.address)

  const toggle = (transport: MapTransport) =>
    setTransports((current) =>
      current.includes(transport)
        ? current.length > 1
          ? current.filter((item) => item !== transport)
          : current
        : ROUTE_TRANSPORTS.filter((item) => item === transport || current.includes(item)),
    )

  return (
    <>
      <AppModal
        isOpen={isOpen && pending == null}
        onClose={onClose}
        title="Параметры маршрута"
        description="Выберите маршрут с учетом пожеланий"
      >
        <div className="flex min-h-0 flex-col gap-3">
          <div className="flex flex-wrap gap-1" role="group" aria-label="Транспорт">
            {ROUTE_TRANSPORTS.map((transport) => {
              const chip = CHIPS[transport]
              const active = transports.includes(transport)
              const ChipIcon = active ? chip.activeIcon : chip.icon
              return (
                <button
                  key={transport}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggle(transport)}
                  className={cn(
                    'inline-flex h-7 cursor-pointer items-center gap-1 px-3 text-sm leading-6 font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-focus/40',
                    active ? 'bg-accent text-accent-foreground hover:bg-accent-hover' : 'bg-surface-tertiary text-foreground hover:bg-default-hover',
                  )}
                  style={{ borderRadius: 8 }}
                >
                  <ChipIcon size={14} />
                  {chip.label}
                </button>
              )
            })}
          </div>

          <div className="-mx-6 max-h-[448px] overflow-y-auto px-6">
            {variants.map((variant) => (
              <button
                key={variant.transport}
                type="button"
                onClick={() => (variant.current ? onClose() : setPending(variant))}
                className="flex w-full cursor-pointer flex-col gap-2 border-b border-border py-3 text-left outline-none last:border-b-0 hover:bg-surface-hover focus-visible:bg-surface-hover"
              >
                <span className="flex w-full items-center gap-2 text-sm leading-5">
                  <span className="min-w-0 flex-1 truncate font-semibold text-foreground">
                    {variant.current ? '' : '≈ '}
                    {formatDuration(variant.totalMinutes)}
                    {variant.current ? <span className="font-normal text-muted"> · текущий</span> : null}
                  </span>
                  {variant.endsAt ? (
                    <span className="shrink-0 text-muted">Завершение в {variant.endsAt}</span>
                  ) : null}
                </span>
                <RouteStepsChain startAddress={engineer.start.address} addresses={addresses} legs={variant.legs} />
              </button>
            ))}
          </div>
        </div>
      </AppModal>

      <AppModal
        isOpen={pending != null}
        onClose={() => setPending(null)}
        icon={<RiErrorWarningLine size={16} />}
        title="Перестроить маршрут?"
        description="Маршрут будет пересчитан с выбранными параметрами. Время прибытия на последующие заявки может измениться"
        footer={
          <>
            <button type="button" onClick={() => setPending(null)} className={buttonClass.outline}>
              Отмена
            </button>
            <button
              type="button"
              autoFocus
              onClick={() => {
                if (pending) {
                  onApply(pending)
                  toast.success('Маршрут перестроен', {
                    description: `${CHIPS[pending.transport].label}, завершение в ${pending.endsAt}`,
                  })
                }
                setPending(null)
                onClose()
              }}
              className={buttonClass.primary}
            >
              Подтвердить
            </button>
          </>
        }
      />
    </>
  )
}
