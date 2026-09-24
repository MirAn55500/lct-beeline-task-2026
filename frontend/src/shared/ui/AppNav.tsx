import { NavLink, useLocation, useSearchParams } from 'react-router'

import {
  isNavItemActive,
  navHelpItem,
  navPrimaryItems,
  type NavItem,
} from '@/shared/config/nav'
import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui/AppPanel'

function NavItemLink({
  item,
  active,
  search,
}: {
  item: NavItem
  active: boolean
  search: string
}) {
  const Icon = item.icon
  // Сохраняем date (и прочие query) при переходах по разделам в рамках сессии.
  const to = search ? `${item.to}${search}` : item.to

  return (
    <NavLink
      to={to}
      className={cn(
        'flex h-9 cursor-pointer items-center gap-3 rounded-lg px-3 text-sm font-medium text-foreground transition-colors hover:bg-[#f5f5f5]',
        active && 'bg-[#f5f5f5]',
      )}
    >
      <Icon size={16} className="shrink-0 text-[#71717a]" />
      <span>{item.label}</span>
    </NavLink>
  )
}

export function AppNav({ className }: { className?: string }) {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const preserved = new URLSearchParams()
  const date = params.get('date')
  if (date) preserved.set('date', date)
  const search = preserved.toString() ? `?${preserved.toString()}` : ''

  return (
    <AppPanel className={cn('flex min-h-0 flex-1 flex-col p-3', className)}>
      <nav className="flex min-h-0 flex-1 flex-col justify-between">
        <div className="flex flex-col gap-2">
          {navPrimaryItems.map((item) => (
            <NavItemLink
              key={item.to}
              item={item}
              active={isNavItemActive(item, pathname)}
              search={search}
            />
          ))}
        </div>

        <NavItemLink
          item={navHelpItem}
          active={isNavItemActive(navHelpItem, pathname)}
          search={search}
        />
      </nav>
    </AppPanel>
  )
}
