import { NavLink } from 'react-router'

import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'

const VIEWS = [
  { to: routes.planGantt, label: 'Гант' },
  { to: routes.planMap, label: 'Карта' },
]

type PlanViewTabsProps = {
  className?: string
}

/** Переключатель вида плана работ из шапки: диаграмма Ганта или карта. */
export function PlanViewTabs({ className }: PlanViewTabsProps) {
  return (
    <nav
      aria-label="Вид плана"
      className={cn('flex h-9 w-[214px] items-center gap-[5px] bg-[#ebebec] px-1.5 py-0.5 min-[1400px]:w-[334px]', className)}
      style={{ borderRadius: 8 }}
    >
      {VIEWS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          replace
          className={({ isActive }) =>
            cn(
              'flex h-8 flex-1 items-center justify-center px-3 text-sm font-medium leading-6 transition-colors',
              isActive
                ? 'bg-white text-[#18181b] shadow-[0_2px_8px_rgb(0_0_0/0.06)]'
                : 'text-[#71717a] hover:text-[#18181b]',
            )
          }
          style={{ borderRadius: 6 }}
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
