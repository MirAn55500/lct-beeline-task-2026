import { NavLink, useLocation } from 'react-router'

import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'
import { SegmentedControl } from '@/shared/ui/SegmentedControl'

const VIEWS = [
  { id: routes.planGantt, label: 'Гант' },
  { id: routes.planMap, label: 'Карта' },
]

type PlanViewTabsProps = {
  className?: string
}

/**
 * Переключатель вида плана работ из шапки: диаграмма Ганта или карта.
 * Регион, день и версия плана лежат в адресе и переезжают вместе с видом.
 */
export function PlanViewTabs({ className }: PlanViewTabsProps) {
  const { pathname, search } = useLocation()
  const value = VIEWS.find((view) => pathname.startsWith(view.id))?.id ?? routes.planGantt

  return (
    <SegmentedControl
      aria-label="Вид плана"
      options={VIEWS}
      value={value}
      className={cn('w-[214px] min-[1400px]:w-[334px]', className)}
      renderOption={(option, { className: segment }) => (
        <NavLink key={option.id} to={{ pathname: option.id, search }} replace className={segment}>
          {option.label}
        </NavLink>
      )}
    />
  )
}
