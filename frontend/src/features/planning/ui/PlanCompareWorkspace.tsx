import { ListBox, Select } from '@heroui/react'
import {
  RiArrowDownSLine,
  RiArrowDownSFill,
  RiArrowUpSFill,
  RiFlashlightFill,
} from '@remixicon/react'
import { skipToken } from '@reduxjs/toolkit/query/react'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import { useDayOverview } from '../lib/useDayOverview'
import { useGetPlanExportQuery, type PlanExportResponse } from '../planApi'
import type { PlanVersion } from '../types'

type PlanKind = 'efficient' | 'baseline' | 'neutral'

type MetricKey = 'assigned' | 'load' | 'engineers' | 'unassigned'

type PlanMetrics = {
  assigned: number
  load: number
  engineersEngaged: number
  engineersTotal: number
  unassigned: number
}

type Trend = {
  better: boolean
  higher: boolean
}

function avgLoad(plan: PlanExportResponse | undefined): number | null {
  if (!plan?.routes.length) return null
  const active = plan.routes.filter((route) => route.visits.length > 0)
  const sample = active.length > 0 ? active : plan.routes
  if (sample.length === 0) return null
  const sum = sample.reduce((acc, route) => acc + route.utilization, 0)
  return Math.round((sum / sample.length) * 100)
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
  }
}

/** Выше лучше: заявки и загрузка. Ниже лучше: инженеры и неназначенные. */
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
  }
}

function trendFor(key: MetricKey, own: number, other: number): Trend | null {
  if (own === other) return null
  const higher = own > other
  const better = isHigherBetter(key) ? higher : !higher
  return { better, higher }
}

/** Кто «эффективнее» по правилу стенда: заявки → инженеры → загрузка → неназначенные. */
function classifyKinds(
  left: PlanMetrics | null,
  right: PlanMetrics | null,
): { left: PlanKind; right: PlanKind } {
  if (!left || !right) return { left: 'neutral', right: 'neutral' }
  if (
    left.assigned === right.assigned &&
    left.engineersEngaged === right.engineersEngaged &&
    left.load === right.load &&
    left.unassigned === right.unassigned
  ) {
    return { left: 'neutral', right: 'neutral' }
  }
  const leftWins =
    left.assigned !== right.assigned
      ? left.assigned > right.assigned
      : left.engineersEngaged !== right.engineersEngaged
        ? left.engineersEngaged < right.engineersEngaged
        : left.load !== right.load
          ? left.load > right.load
          : left.unassigned < right.unassigned
  return leftWins
    ? { left: 'efficient', right: 'baseline' }
    : { left: 'baseline', right: 'efficient' }
}

function PlanKindBadge({ kind }: { kind: PlanKind }) {
  if (kind === 'neutral') return null
  const efficient = kind === 'efficient'
  return (
    <span
      className={cn(
        'inline-flex h-6 shrink-0 items-center gap-1 px-1.5 text-xs font-medium leading-5',
        efficient ? 'bg-success-soft text-success-soft-foreground' : 'bg-surface-tertiary text-foreground',
      )}
      style={{ borderRadius: 4 }}
    >
      {efficient ? (
        <RiFlashlightFill size={12} className="shrink-0" />
      ) : (
        <span aria-hidden className="inline-flex w-3 justify-center text-xs font-semibold leading-none">
          =
        </span>
      )}
      {efficient ? 'Эффективный' : 'Базовый'}
    </span>
  )
}

function MetricCard({
  value,
  label,
  trend,
}: {
  value: string
  label: string
  trend: Trend | null
}) {
  return (
    <div
      className="relative flex min-h-[120px] flex-col justify-between bg-surface-secondary p-4"
      style={{ borderRadius: 12 }}
    >
      {trend ? (
        <span
          className={cn(
            'absolute top-3 right-3',
            trend.better ? 'text-success' : 'text-danger',
          )}
          aria-hidden
        >
          {trend.higher ? <RiArrowUpSFill size={18} /> : <RiArrowDownSFill size={18} />}
        </span>
      ) : null}
      <p className="pr-6 text-4xl font-semibold leading-none text-foreground">{value}</p>
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
  const selected = plans.find((item) => item.plan_id === value)
  const label = selected ? `План №${selected.version}` : 'План'

  return (
    <Select
      aria-label="Версия плана"
      className="min-w-0"
      placeholder="План"
      value={value ?? undefined}
      onChange={(key) => {
        if (key != null) onChange(key as number)
      }}
    >
      <Select.Trigger className="flex cursor-pointer items-center gap-1 bg-transparent p-0 shadow-none outline-none">
        <Select.Value className="text-base font-semibold leading-6 text-foreground">
          {() => label}
        </Select.Value>
        <Select.Indicator className="shrink-0 text-foreground">
          <RiArrowDownSLine size={18} />
        </Select.Indicator>
      </Select.Trigger>
      <Select.Popover
        className="min-w-[200px] border border-border bg-surface p-1 shadow-lg outline-none"
        style={{ borderRadius: 16 }}
      >
        <ListBox className="outline-none">
          {plans.map((plan) => (
            <ListBox.Item
              key={plan.plan_id}
              id={plan.plan_id}
              textValue={`План №${plan.version}`}
              className="cursor-pointer px-3 py-2 text-sm text-foreground outline-none data-[focused]:bg-surface-hover data-[selected]:bg-surface-hover"
              style={{ borderRadius: 8 }}
            >
              {`План №${plan.version}`}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  )
}

function PlanColumn({
  plans,
  planId,
  onPlanIdChange,
  kind,
  metrics,
  other,
}: {
  plans: PlanVersion[]
  planId: number | null
  onPlanIdChange: (planId: number) => void
  kind: PlanKind
  metrics: PlanMetrics | null
  other: PlanMetrics | null
}) {
  const cards: { key: MetricKey; value: string; label: string }[] = metrics
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
          value: `${metrics.engineersEngaged} из ${metrics.engineersTotal}`,
          label: 'Инженеров задействовано',
        },
        {
          key: 'unassigned',
          value: String(metrics.unassigned),
          label: 'Заявки не назначено',
        },
      ]
    : []

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <PlanSelect plans={plans} value={planId} onChange={onPlanIdChange} />
        <PlanKindBadge kind={kind} />
      </div>
      {metrics ? (
        <div className="grid grid-cols-2 gap-3">
          {cards.map((card) => (
            <MetricCard
              key={card.key}
              value={card.value}
              label={card.label}
              trend={
                other
                  ? trendFor(card.key, metricValue(metrics, card.key), metricValue(other, card.key))
                  : null
              }
            />
          ))}
        </div>
      ) : (
        <div
          className="flex min-h-[260px] items-center justify-center bg-surface-secondary px-4 text-sm text-muted"
          style={{ borderRadius: 12 }}
        >
          Нет данных по выбранному плану
        </div>
      )}
    </div>
  )
}

type PlanCompareWorkspaceProps = {
  regionId: number | null
  date: string
  className?: string
}

export function PlanCompareWorkspace({ regionId, date, className }: PlanCompareWorkspaceProps) {
  const [params, setParams] = useSearchParams()
  const { data: overview } = useDayOverview(
    { regionId: regionId ?? 0, date },
    { skip: regionId == null || !date },
  )
  const plans = overview?.plans ?? []
  const engineersTotal = overview?.engineers.total ?? 0

  const leftFromUrl = Number(params.get('left'))
  const rightFromUrl = Number(params.get('right'))

  const defaultLeft = plans[0]?.plan_id ?? null
  const defaultRight = plans[1]?.plan_id ?? plans[0]?.plan_id ?? null

  const [leftId, setLeftId] = useState<number | null>(null)
  const [rightId, setRightId] = useState<number | null>(null)

  useEffect(() => {
    if (plans.length === 0) {
      setLeftId(null)
      setRightId(null)
      return
    }
    setLeftId((current) => {
      if (plans.some((item) => item.plan_id === leftFromUrl)) return leftFromUrl
      if (current != null && plans.some((item) => item.plan_id === current)) return current
      return defaultLeft
    })
    setRightId((current) => {
      if (plans.some((item) => item.plan_id === rightFromUrl)) return rightFromUrl
      if (current != null && plans.some((item) => item.plan_id === current)) return current
      return defaultRight
    })
  }, [plans, leftFromUrl, rightFromUrl, defaultLeft, defaultRight])

  const writePair = (left: number | null, right: number | null) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (left != null) next.set('left', String(left))
        else next.delete('left')
        if (right != null) next.set('right', String(right))
        else next.delete('right')
        return next
      },
      { replace: true },
    )
  }

  const leftQuery =
    regionId != null && leftId != null
      ? { regionId, date, planId: leftId }
      : skipToken
  const rightQuery =
    regionId != null && rightId != null
      ? { regionId, date, planId: rightId }
      : skipToken

  const leftPlan = useGetPlanExportQuery(leftQuery)
  const rightPlan = useGetPlanExportQuery(rightQuery)

  const leftMetrics = useMemo(
    () => metricsFromPlan(leftPlan.data, engineersTotal),
    [leftPlan.data, engineersTotal],
  )
  const rightMetrics = useMemo(
    () => metricsFromPlan(rightPlan.data, engineersTotal),
    [rightPlan.data, engineersTotal],
  )
  const kinds = classifyKinds(leftMetrics, rightMetrics)

  return (
    <AppPanel className={cn('flex min-h-0 flex-1 flex-col gap-5 p-5', className)}>
      <h2 className="shrink-0 text-xl font-semibold leading-7 text-foreground">Сравнение планов</h2>

      {regionId == null || !date ? (
        <p className="text-sm text-muted">Выберите регион и день в шапке.</p>
      ) : plans.length === 0 ? (
        <p className="text-sm text-muted">На этот день ещё нет версий плана.</p>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-2">
          <PlanColumn
            plans={plans}
            planId={leftId}
            onPlanIdChange={(id) => {
              setLeftId(id)
              writePair(id, rightId)
            }}
            kind={kinds.left}
            metrics={leftMetrics}
            other={rightMetrics}
          />
          <PlanColumn
            plans={plans}
            planId={rightId}
            onPlanIdChange={(id) => {
              setRightId(id)
              writePair(leftId, id)
            }}
            kind={kinds.right}
            metrics={rightMetrics}
            other={leftMetrics}
          />
        </div>
      )}
    </AppPanel>
  )
}
