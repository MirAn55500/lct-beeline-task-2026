import {
  RiArrowDownSLine,
  RiArrowDownSFill,
  RiArrowUpSFill,
  RiFlashlightFill,
} from '@remixicon/react'
import { skipToken } from '@reduxjs/toolkit/query/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'

import { cn } from '@/shared/lib/cn'
import { AppPanel, SegmentedControl, type SegmentedOption } from '@/shared/ui'

import { planHours } from '../lib/planHours'
import { avgDistance, avgLoad, formatKm, totalDistance } from '../lib/planMetrics'
import { useDayOverview } from '../lib/useDayOverview'
import { useGetPlanExportQuery, type PlanExportResponse } from '../planApi'
import type { PlanVersion } from '../types'
import { PlanLoadingBadge } from './PlanLoadingBadge'
import { PlanMiniGantt } from './PlanMiniGantt'

/** Какой расчёт версии показывать: сам план или базовый план при нём. */
type PlanVariant = 'efficient' | 'baseline'

type MetricKey = 'assigned' | 'load' | 'engineers' | 'unassigned' | 'distance' | 'kmPerTicket'

type PlanMetrics = {
  assigned: number
  load: number
  engineersEngaged: number
  engineersTotal: number
  unassigned: number
  /** Километры округлены как на экране: стрелка сравнения — только при видимой разнице. */
  distance: number
  kmPerTicket: number
}

type Trend = {
  better: boolean
  higher: boolean
}

function metricsFromPlan(
  plan: PlanExportResponse | undefined,
  engineersTotal: number,
): PlanMetrics | null {
  if (!plan) return null
  const assigned = plan.routes.reduce((acc, route) => acc + route.visits.length, 0)
  const engineersEngaged = plan.routes.filter((route) => route.visits.length > 0).length
  const load = avgLoad(plan) ?? 0
  return {
    assigned,
    load,
    engineersEngaged,
    engineersTotal: engineersTotal || plan.engineers.length,
    unassigned: plan.unassigned.length,
    distance: Math.round(totalDistance(plan) ?? 0),
    kmPerTicket: Math.round((avgDistance(plan) ?? 0) * 10) / 10,
  }
}

/** Выше лучше: заявки и загрузка. Ниже лучше: инженеры, неназначенные и километры. */
function isHigherBetter(key: MetricKey) {
  return key === 'assigned' || key === 'load'
}

function metricValue(metrics: PlanMetrics, key: MetricKey): number {
  switch (key) {
    case 'assigned':
      return metrics.assigned
    case 'load':
      return metrics.load
    case 'engineers':
      return metrics.engineersEngaged
    case 'unassigned':
      return metrics.unassigned
    case 'distance':
      return metrics.distance
    case 'kmPerTicket':
      return metrics.kmPerTicket
  }
}

function trendFor(key: MetricKey, own: number, other: number): Trend | null {
  if (own === other) return null
  const higher = own > other
  const better = isHigherBetter(key) ? higher : !higher
  return { better, higher }
}

const VARIANTS: SegmentedOption<PlanVariant>[] = [
  { id: 'efficient', label: 'Эффективный' },
  { id: 'baseline', label: 'Базовый' },
]

/** У «Базовой» версии эффективного расчёта нет — она сама базовая. */
function variantOf(plan: PlanVersion | undefined, wanted: PlanVariant): PlanVariant {
  return plan?.distribution === 'even' ? 'baseline' : wanted
}

function VariantSwitch({
  value,
  onlyBaseline,
  onChange,
}: {
  value: PlanVariant
  onlyBaseline: boolean
  onChange: (variant: PlanVariant) => void
}) {
  return (
    <SegmentedControl
      aria-label="Расчёт"
      options={VARIANTS}
      value={value}
      renderOption={(option, props) => {
        const disabled = onlyBaseline && option.id === 'efficient'
        return (
          <button
            type="button"
            role="tab"
            aria-selected={props.active}
            disabled={disabled}
            title={disabled ? 'Версия составлена базовым алгоритмом — эффективного расчёта у неё нет' : undefined}
            onClick={() => onChange(option.id)}
            className={cn(props.className, 'flex-none', disabled && 'cursor-not-allowed opacity-40')}
          >
            {option.id === 'efficient' ? (
              <span className="inline-flex items-center gap-1">
                <RiFlashlightFill size={12} className="shrink-0" />
                {option.label}
              </span>
            ) : (
              option.label
            )}
          </button>
        )
      }}
    />
  )
}

function MetricCard({
  value,
  unit,
  label,
  trend,
}: {
  value: string
  unit?: string
  label: string
  trend: Trend | null
}) {
  return (
    <div
      className="relative flex min-h-[112px] min-w-0 flex-col justify-between gap-2 bg-surface-secondary p-3"
      style={{ borderRadius: 12 }}
    >
      {trend ? (
        <span
          className={cn(
            'absolute top-2 right-2',
            trend.better ? 'text-success' : 'text-danger',
          )}
          aria-hidden
        >
          {trend.higher ? <RiArrowUpSFill size={18} /> : <RiArrowDownSFill size={18} />}
        </span>
      ) : null}
      <p className="flex items-baseline gap-1 pr-5 font-semibold leading-none whitespace-nowrap text-foreground">
        <span className="text-3xl">{value}</span>
        {unit ? <span className="text-base">{unit}</span> : null}
      </p>
      <p className="text-sm leading-5 text-muted">{label}</p>
    </div>
  )
}

function PlanSelect({
  plans,
  value,
  onChange,
}: {
  plans: PlanVersion[]
  value: number | null
  onChange: (planId: number) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selected = plans.find((item) => item.plan_id === value)
  // Одну версию можно выбрать в обеих колонках: сам план против своего базового.
  const options = plans
  const label = selected ? `План №${selected.version}` : 'План'

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-label="Версия плана"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="inline-flex cursor-pointer items-center gap-1 text-left text-base font-semibold leading-6 text-foreground transition-colors hover:opacity-80"
      >
        <span>{label}</span>
        <RiArrowDownSLine
          size={20}
          className={cn('shrink-0 transition-transform', open && 'rotate-180')}
        />
      </button>
      {open ? (
        <div
          className="absolute top-[calc(100%+8px)] left-0 z-50 min-w-[160px] border border-border bg-surface p-1 shadow-lg"
          style={{ borderRadius: 16 }}
        >
          {options.length === 0 ? (
            <p className="px-3 py-2 text-sm text-muted">Нет версий</p>
          ) : (
            options.map((plan) => (
              <button
                key={plan.plan_id}
                type="button"
                onClick={() => {
                  onChange(plan.plan_id)
                  setOpen(false)
                }}
                className={cn(
                  'flex h-9 w-full cursor-pointer items-center rounded-lg px-3 text-sm font-medium text-foreground transition-colors hover:bg-surface-hover',
                  plan.plan_id === value && 'bg-surface-hover',
                )}
              >
                {`План №${plan.version}`}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}

function PlanColumn({
  plans,
  planId,
  variant,
  onPlanIdChange,
  onVariantChange,
  plan,
  loading,
  error,
  hours,
  metrics,
  other,
}: {
  plans: PlanVersion[]
  planId: number | null
  variant: PlanVariant
  onPlanIdChange: (planId: number) => void
  onVariantChange: (variant: PlanVariant) => void
  plan: PlanExportResponse | undefined
  loading: boolean
  /** Базового плана при версии нет — старая версия, до базовых расчётов. */
  error: string | null
  hours: [number, number]
  metrics: PlanMetrics | null
  other: PlanMetrics | null
}) {
  const version = plans.find((item) => item.plan_id === planId)
  const cards: { key: MetricKey; value: string; unit?: string; label: string }[] = metrics
    ? [
        {
          key: 'assigned',
          value: String(metrics.assigned),
          label: 'Заявок назначено',
        },
        {
          key: 'load',
          value: `${metrics.load}%`,
          label: 'Средняя загрузка',
        },
        {
          key: 'engineers',
          value: String(metrics.engineersEngaged),
          unit: `из ${metrics.engineersTotal}`,
          label: 'Инженеров задействовано',
        },
        {
          key: 'unassigned',
          value: String(metrics.unassigned),
          label: 'Заявки не назначено',
        },
        {
          key: 'distance',
          value: String(metrics.distance),
          unit: 'км',
          label: 'Общий пробег',
        },
        {
          key: 'kmPerTicket',
          value: formatKm(metrics.kmPerTicket),
          unit: 'км',
          label: 'Среднее на заявку',
        },
      ]
    : []

  return (
    <div className="relative flex min-w-0 flex-1 flex-col gap-4">
      <PlanLoadingBadge active={loading && plan != null} />
      <div className="flex items-center justify-between gap-3">
        <PlanSelect plans={plans} value={planId} onChange={onPlanIdChange} />
        <VariantSwitch
          value={variant}
          onlyBaseline={version?.distribution === 'even'}
          onChange={onVariantChange}
        />
      </div>
      {metrics && plan ? (
        <>
          <div className="grid grid-cols-3 gap-3">
            {cards.map((card) => (
              <MetricCard
                key={card.key}
                value={card.value}
                unit={card.unit}
                label={card.label}
                trend={
                  other
                    ? trendFor(card.key, metricValue(metrics, card.key), metricValue(other, card.key))
                    : null
                }
              />
            ))}
          </div>
          <PlanMiniGantt plan={plan} fromHour={hours[0]} toHour={hours[1]} />
        </>
      ) : (
        <div
          className="flex min-h-[260px] items-center justify-center bg-surface-secondary px-4 text-center text-sm text-muted"
          style={{ borderRadius: 12 }}
        >
          {loading ? 'Загружаем план' : (error ?? 'Нет данных по выбранному плану')}
        </div>
      )}
    </div>
  )
}

type Side = { planId: number | null; variant: PlanVariant }

const sameSide = (a: Side, b: Side) => a.planId === b.planId && a.variant === b.variant

const readVariant = (raw: string | null): PlanVariant | null =>
  raw === 'efficient' || raw === 'baseline' ? raw : null

/** 404 — при версии нет базового плана; остальное — общий текст. */
function loadError(error: unknown): string {
  const status = (error as { status?: unknown } | undefined)?.status
  return status === 404
    ? 'Для этой версии базовый план не сохранялся — обновите план'
    : 'Не удалось загрузить план'
}

type PlanCompareWorkspaceProps = {
  regionId: number | null
  date: string
  className?: string
}

/**
 * Сравнение планов дня. В каждой колонке — версия и расчёт: сам план («Эффективный»)
 * или базовый план при нём (алгоритм ТЗ по тем же данным). Метрики со стрелками
 * «лучше/хуже» и мини-Гант только для просмотра. По умолчанию — последняя версия против
 * своего базового плана.
 */
export function PlanCompareWorkspace({ regionId, date, className }: PlanCompareWorkspaceProps) {
  const [params, setParams] = useSearchParams()
  const { data: overview } = useDayOverview(
    { regionId: regionId ?? 0, date },
    { skip: regionId == null || !date },
  )
  const plans = useMemo(() => overview?.plans ?? [], [overview?.plans])
  const engineersTotal = overview?.engineers.total ?? 0
  const byId = (id: number | null) => plans.find((item) => item.plan_id === id)

  // Выбор живёт в адресе: ссылкой на сравнение можно поделиться, «назад» его помнит.
  const known = (raw: string | null) => {
    const id = Number(raw)
    return plans.some((item) => item.plan_id === id) ? id : null
  }
  const latest = plans[0]?.plan_id ?? null
  const leftId = known(params.get('left')) ?? latest
  const left: Side = {
    planId: leftId,
    variant: variantOf(byId(leftId), readVariant(params.get('lv')) ?? 'efficient'),
  }
  let right: Side = {
    planId: known(params.get('right')) ?? latest,
    variant: variantOf(byId(known(params.get('right')) ?? latest), readVariant(params.get('rv')) ?? 'baseline'),
  }
  if (params.get('right') == null && sameSide(left, right)) {
    // Последняя версия — «Базовая», своего базового у неё нет: справа — предыдущая версия.
    const other = plans.find((item) => item.plan_id !== leftId)?.plan_id ?? null
    if (other != null) right = { planId: other, variant: variantOf(byId(other), 'efficient') }
  }

  const change = (key: 'left' | 'right', patch: Partial<Side>) => {
    const own = { ...(key === 'left' ? left : right), ...patch }
    own.variant = variantOf(byId(own.planId), own.variant)
    const next = key === 'left' ? { left: own, right } : { left, right: own }
    setParams(
      (prev) => {
        const query = new URLSearchParams(prev)
        for (const [name, variantName, side] of [
          ['left', 'lv', next.left],
          ['right', 'rv', next.right],
        ] as const) {
          if (side.planId != null) query.set(name, String(side.planId))
          else query.delete(name)
          query.set(variantName, side.variant)
        }
        return query
      },
      { replace: true },
    )
  }

  const queryFor = (side: Side) =>
    regionId != null && side.planId != null
      ? {
          regionId,
          date,
          planId: side.planId,
          // У «Базовой» версии базовый план — она сама.
          baseline: side.variant === 'baseline' && byId(side.planId)?.distribution !== 'even',
        }
      : skipToken

  const leftPlan = useGetPlanExportQuery(queryFor(left))
  const rightPlan = useGetPlanExportQuery(queryFor(right))
  const leftData = leftPlan.currentData
  const rightData = rightPlan.currentData

  const leftMetrics = useMemo(() => metricsFromPlan(leftData, engineersTotal), [leftData, engineersTotal])
  const rightMetrics = useMemo(() => metricsFromPlan(rightData, engineersTotal), [rightData, engineersTotal])
  // Одна шкала на обе ленты: одно и то же время — на одной вертикали.
  const hours = useMemo(() => planHours([leftData, rightData]), [leftData, rightData])
  const canCompare = !sameSide(left, right)

  return (
    <AppPanel className={cn('flex min-h-0 flex-1 flex-col gap-5 p-5', className)}>
      <h2 className="shrink-0 text-xl font-semibold leading-7 text-foreground">Сравнение планов</h2>

      {regionId == null || !date ? (
        <p className="text-sm text-muted">Выберите регион и день в шапке.</p>
      ) : plans.length === 0 ? (
        <p className="text-sm text-muted">На этот день ещё нет версий плана.</p>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 content-start gap-6 overflow-y-auto lg:grid-cols-2">
          <PlanColumn
            plans={plans}
            planId={left.planId}
            variant={left.variant}
            onPlanIdChange={(planId) => change('left', { planId })}
            onVariantChange={(variant) => change('left', { variant })}
            plan={leftData}
            loading={leftPlan.isFetching}
            error={leftPlan.isError ? loadError(leftPlan.error) : null}
            hours={hours}
            metrics={leftMetrics}
            other={canCompare ? rightMetrics : null}
          />
          <PlanColumn
            plans={plans}
            planId={right.planId}
            variant={right.variant}
            onPlanIdChange={(planId) => change('right', { planId })}
            onVariantChange={(variant) => change('right', { variant })}
            plan={rightData}
            loading={rightPlan.isFetching}
            error={rightPlan.isError ? loadError(rightPlan.error) : null}
            hours={hours}
            metrics={rightMetrics}
            other={canCompare ? leftMetrics : null}
          />
        </div>
      )}
    </AppPanel>
  )
}
