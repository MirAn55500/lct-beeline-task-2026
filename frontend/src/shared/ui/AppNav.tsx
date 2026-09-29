import { NavLink, useLocation, useSearchParams } from 'react-router'

import {
  isNavItemActive,
  navHelpItem,
  navPrimaryItems,
  type NavItem,
} from '@/shared/config/nav'
import { cn } from '@/shared/lib/cn'
import { preservedContextSearch } from '@/shared/lib/sessionContext'
import { AppPanel } from '@/shared/ui/AppPanel'
import { resetGeneralOnboarding } from '@/shared/ui/GeneralOnboarding'

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
  // Регион и день из адреса или sessionStorage — чтобы не сбрасывались между разделами.
  const to = search ? `${item.to}${search}` : item.to

  return (
    <NavLink
      to={to}
      onClick={item.to === navHelpItem.to ? resetGeneralOnboarding : undefined}
      className={cn(
        'flex h-9 cursor-pointer items-center gap-3 rounded-lg px-3 text-sm font-medium text-foreground transition-colors hover:bg-surface-hover',
        active && 'bg-surface-hover',
      )}
    >
      <Icon size={16} className="shrink-0 text-muted" />
      <span>{item.label}</span>
    </NavLink>
  )
}

export function AppNav({ className }: { className?: string }) {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const search = preservedContextSearch(params)

  return (
    <AppPanel
      data-onboarding="main-navigation"
      className={cn('flex min-h-0 flex-1 flex-col p-3', className)}
    >
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
