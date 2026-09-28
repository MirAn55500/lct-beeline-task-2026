import { useMemo, useState } from 'react'
import { ListBox, Select } from '@heroui/react'
import {
  RiArrowDownSFill,
  RiArrowDownSLine,
  RiArrowUpSFill,
  RiFlashlightLine,
  RiSubtractLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import { useDayOverview } from '../lib/useDayOverview'
import { getPlanMetrics, type PlanMetrics } from '../lib/planMetrics'
import { useGetPlanExportQuery } from '../planApi'

type Props = {
  className?: string
  regionId: number | null
  date: string
}

type MetricKey = 'assigned' | 'averageLoad' | 'engaged' | 'unassigned'

const METRICS: { key: MetricKey; label: string; lowerIsBetter?: boolean }[] = [
  { key: 'assigned', label: 'Заявок назначено' },
  { key: 'averageLoad', label: 'Средняя загрузка' },
  { key: 'engaged', label: 'Инженеров задействовано', lowerIsBetter: true },
  { key: 'unassigned', label: 'Заявки не назначено', lowerIsBetter: true },
]

function MetricCard({
  metric,
  value,
  other,
  metrics,
}: {
  metric: (typeof METRICS)[number]
  value: number
  other: number
  metrics: PlanMetrics
}) {
  const delta = value - other
  const isBetter = metric.lowerIsBetter ? delta < 0 : delta > 0
  const Arrow = delta === 0 ? RiSubtractLine : delta > 0 ? RiArrowUpSFill : RiArrowDownSFill
  const suffix = metric.key === 'averageLoad' ? '%' : ''

  return (
    <div className="relative flex h-20 min-w-0 flex-col justify-between rounded-lg bg-background px-3 py-2">
      <div className="flex items-baseline gap-1 text-4xl font-semibold leading-10 text-foreground">
        <span>{value}{suffix}</span>
        {metric.key === 'engaged' ? (
          <span className="text-base leading-6">из {metrics.engineers}</span>
        ) : null}
      </div>
      <p className="truncate text-sm leading-5 text-foreground">{metric.label}</p>
      <Arrow
        size={18}
        aria-label={delta === 0 ? 'Без изменений' : isBetter ? 'Показатель лучше' : 'Показатель хуже'}
        className={cn(
          'absolute right-2 top-2',
          delta === 0 ? 'text-muted' : isBetter ? 'text-success' : 'text-danger',
        )}
      />
    </div>
  )
}

function PlanColumn({
  planId,
  plans,
  label,
  tone,
  metrics,
  otherMetrics,
  onChange,
}: {
  planId: number
  plans: { plan_id: number; version: number }[]
  label: string
  tone: 'efficient' | 'baseline'
  metrics: PlanMetrics
  otherMetrics: PlanMetrics
  onChange: (id: number) => void
}) {
  return (
    <section className="min-w-0 flex-1">
      <div className="mb-2 flex h-6 items-center justify-between gap-3">
        <Select
          value={planId}
          onChange={(key) => {
            if (key != null) onChange(Number(key))
          }}
          aria-label={`${label}: версия плана`}
          className="w-auto min-w-0"
        >
          <Select.Trigger className="flex cursor-pointer items-center gap-1 bg-transparent text-left text-base font-semibold leading-6 text-foreground outline-none transition-colors hover:opacity-80">
            <Select.Value className="min-w-0 truncate" />
            <Select.Indicator className="shrink-0 text-foreground">
              <RiArrowDownSLine size={20} />
            </Select.Indicator>
          </Select.Trigger>
          <Select.Popover
            className="min-w-[193px] bg-surface p-1 shadow-lg outline-none"
            style={{ borderRadius: 16 }}
          >
            <ListBox className="outline-none">
              {plans.map((plan) => (
                <ListBox.Item
                  key={plan.plan_id}
                  id={plan.plan_id}
                  textValue={`План №${plan.version}`}
                  className="cursor-pointer px-3 py-2 text-sm font-medium leading-5 text-foreground outline-none data-[focused]:bg-surface-hover data-[selected]:bg-surface-hover"
                  style={{ borderRadius: 8 }}
                >
                  План №{plan.version}
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
        <span className="inline-flex items-center gap-1 text-xs font-medium leading-5 text-foreground">
          {tone === 'efficient' ? <RiFlashlightLine size={12} /> : <RiSubtractLine size={12} />}
          {label}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {METRICS.map((metric) => (
          <MetricCard
            key={metric.key}
            metric={metric}
            value={metrics[metric.key]}
            other={otherMetrics[metric.key]}
            metrics={metrics}
          />
        ))}
      </div>
    </section>
  )
}

export function PlanComparisonWorkspace({ className, regionId, date }: Props) {
  const { data: overview, isFetching } = useDayOverview(
    { regionId: regionId ?? 0, date },
    { skip: regionId == null || !date },
  )
  const plans = useMemo(() => overview?.plans ?? [], [overview?.plans])
  const [leftId, setLeftId] = useState<number | null>(null)
  const [rightId, setRightId] = useState<number | null>(null)

  const selectedLeftId = plans.some((plan) => plan.plan_id === leftId)
    ? leftId
    : (plans[0]?.plan_id ?? null)
  const selectedRightId = plans.some((plan) => plan.plan_id === rightId)
    ? rightId
    : (plans[1]?.plan_id ?? plans[0]?.plan_id ?? null)

  const leftQuery = useGetPlanExportQuery(
    { regionId: regionId ?? 0, date, planId: selectedLeftId },
    { skip: regionId == null || selectedLeftId == null },
  )
  const rightQuery = useGetPlanExportQuery(
    { regionId: regionId ?? 0, date, planId: selectedRightId },
    { skip: regionId == null || selectedRightId == null },
  )
  const leftMetrics = getPlanMetrics(leftQuery.data)
  const rightMetrics = getPlanMetrics(rightQuery.data)
  const loading = isFetching || leftQuery.isFetching || rightQuery.isFetching

  return (
    <AppPanel className={cn('min-h-0 flex-1 px-5 py-5', className)}>
      <h1 className="text-xl font-semibold leading-7 text-foreground">Сравнение планов</h1>
      <div className="my-4 h-px bg-separator" />

      {plans.length < 2 ? (
        <div className="flex min-h-48 items-center justify-center text-sm text-muted">
          {loading ? 'Загружаем планы…' : 'Для сравнения нужно как минимум два плана'}
        </div>
      ) : selectedLeftId != null && selectedRightId != null && leftMetrics && rightMetrics ? (
        <div className="flex gap-8">
          <PlanColumn
            planId={selectedLeftId}
            plans={plans}
            label="Эффективный"
            tone="efficient"
            metrics={leftMetrics}
            otherMetrics={rightMetrics}
            onChange={setLeftId}
          />
          <PlanColumn
            planId={selectedRightId}
            plans={plans}
            label="Базовый"
            tone="baseline"
            metrics={rightMetrics}
            otherMetrics={leftMetrics}
            onChange={setRightId}
          />
        </div>
      ) : (
        <div className="flex min-h-48 items-center justify-center text-sm text-muted">
          Загружаем сравнение…
        </div>
      )}
    </AppPanel>
  )
}
