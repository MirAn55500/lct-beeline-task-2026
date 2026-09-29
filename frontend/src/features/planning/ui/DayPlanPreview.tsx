import { useMemo } from 'react'

import { cn } from '@/shared/lib/cn'

import { planHours } from '../lib/planHours'
import type { PlanExportResponse } from '../planApi'
import { PlanLoadingBadge } from './PlanLoadingBadge'
import { PlanMiniGantt } from './PlanMiniGantt'

type DayPlanPreviewProps = {
  className?: string
  /** Выбранная версия плана — та же выгрузка, что у Ганта и карты. */
  plan?: PlanExportResponse
  loading?: boolean
}

/**
 * «График» в обзоре дня: мини-Гант выбранной версии — фактическое расписание визитов
 * с дорогой и обедами, а не окна клиентов.
 */
export function DayPlanPreview({
  className,
  plan,
  loading = false,
}: DayPlanPreviewProps) {
  const [fromHour, toHour] = useMemo(() => planHours([plan]), [plan])

  return (
    <div className={cn('relative flex min-h-0 w-full flex-1 flex-col', className)}>
      <PlanLoadingBadge active={loading && plan != null} />
      <h2 className="shrink-0 px-5 pt-5 pb-3 text-xl font-semibold leading-7 text-foreground">
        График
      </h2>

      {plan ? (
        <PlanMiniGantt plan={plan} fromHour={fromHour} toHour={toHour} className="mx-5 mb-5 min-h-0" />
      ) : (
        <p className="px-5 py-6 text-sm leading-6 text-muted">
          {loading ? 'Загружаем план' : 'Назначений пока нет'}
        </p>
      )}
    </div>
  )
}
