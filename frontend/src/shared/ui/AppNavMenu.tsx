import { NavLink, useLocation, useSearchParams } from 'react-router'

import { isNavItemActive, navMenuGroups, type NavItem } from '@/shared/config/nav'
import { cn } from '@/shared/lib/cn'
import { preservedContextSearch } from '@/shared/lib/sessionContext'
import { routes } from '@/shared/config/routes'
import { startGeneralOnboarding } from '@/shared/ui/GeneralOnboarding'

function MenuItem({
  item,
  active,
  search,
  onNavigate,
}: {
  item: NavItem
  active: boolean
  search: string
  onNavigate?: () => void
}) {
  const Icon = item.icon
  const to = search ? `${item.to}${search}` : item.to
  const className = cn(
    'flex h-9 w-full cursor-pointer items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-foreground transition-colors hover:bg-surface-hover',
    active && 'bg-surface-hover',
  )

  if (item.to === routes.help) {
    return (
      <button
        type="button"
        className={className}
        onClick={() => {
          startGeneralOnboarding()
          onNavigate?.()
        }}
      >
        <Icon size={16} className="shrink-0 text-muted" />
        <span>{item.label}</span>
      </button>
    )
  }

  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={className}
    >
      <Icon size={16} className="shrink-0 text-muted" />
      <span>{item.label}</span>
    </NavLink>
  )
}

type AppNavMenuProps = {
  onNavigate?: () => void
  className?: string
}

export function AppNavMenu({ onNavigate, className }: AppNavMenuProps) {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const search = preservedContextSearch(params)

  return (
    <div
      className={cn(
        'w-[322px] rounded-[var(--border-radius-panel)] bg-surface p-3 shadow-lg',
        className,
      )}
    >
      <nav className="flex flex-col gap-2">
        {navMenuGroups.map((group, groupIndex) => (
          <div key={groupIndex} className="flex flex-col gap-2">
            {groupIndex > 0 ? <div className="mx-2 h-px bg-separator" /> : null}
            <div className="flex flex-col gap-2">
              {group.map((item) => (
                <MenuItem
                  key={item.to}
                  item={item}
                  active={isNavItemActive(item, pathname)}
                  search={search}
                  onNavigate={onNavigate}
                />
              ))}
            </div>
          </div>
        ))}
      </nav>
    </div>
  )
}
