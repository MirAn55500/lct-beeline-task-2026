import { Fragment, type ComponentType } from 'react'
import {
  RiArrowRightSFill,
  RiBus2Fill,
  RiCarLine,
  RiRidingLine,
  RiSubwayFill,
  RiTrainFill,
  RiWalkLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

import type { RouteStep } from '../../lib/routeSteps'

type Icon = ComponentType<{ size?: number | string; className?: string }>

const STEP_ICON: Record<RouteStep['kind'], Icon> = {
  walk: RiWalkLine,
  car: RiCarLine,
  bike: RiRidingLine,
  metro: RiSubwayFill,
  bus: RiBus2Fill,
  tram: RiTrainFill,
  train: RiTrainFill,
  public: RiBus2Fill,
}

/** Шаг пути: пешком / на машине — значок и минуты; поездка — цветная плашка с номером линии. */
export function RouteStepChip({ step }: { step: RouteStep }) {
  const StepIcon = STEP_ICON[step.kind]
  if (step.label) {
    return (
      <span
        title={`${step.minutes} мин`}
        className="inline-flex h-5 shrink-0 items-center gap-0.5 px-1 text-sm leading-5 font-medium text-[var(--beeline-white)]"
        style={{ borderRadius: 6, background: step.color ?? 'var(--muted)' }}
      >
        <StepIcon size={14} />
        {step.label}
      </span>
    )
  }
  return (
    <span className="inline-flex h-5 shrink-0 items-center gap-0.5 text-sm leading-5 font-medium whitespace-nowrap text-muted">
      <StepIcon size={14} />
      {step.minutes} мин
    </span>
  )
}

function AddressChip({ children, start = false }: { children: string; start?: boolean }) {
  return (
    <span
      title={children}
      className={cn(
        'inline-block h-5 max-w-[181px] truncate px-1.5 text-sm leading-5 font-medium text-[var(--beeline-white)]',
        start ? 'bg-[#ef4444]' : 'bg-[#64748b]',
      )}
      style={{ borderRadius: 6 }}
    >
      {children}
    </span>
  )
}

function Arrow() {
  return <RiArrowRightSFill size={14} aria-hidden className="shrink-0 text-muted" />
}

/** Цепочка «старт › шаги › заявка › шаги › заявка…» — как список в «Параметрах маршрута». */
export function RouteStepsChain({
  startAddress,
  addresses,
  legs,
  className,
}: {
  startAddress: string
  addresses: string[]
  legs: RouteStep[][]
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-center gap-x-1 gap-y-1', className)}>
      <AddressChip start>{startAddress}</AddressChip>
      {addresses.map((address, index) => (
        <Fragment key={index}>
          {(legs[index] ?? []).map((step, stepIndex) => (
            <Fragment key={stepIndex}>
              <Arrow />
              <RouteStepChip step={step} />
            </Fragment>
          ))}
          <Arrow />
          <AddressChip>{address}</AddressChip>
        </Fragment>
      ))}
    </div>
  )
}
