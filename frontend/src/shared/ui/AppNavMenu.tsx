import { NavLink, useLocation } from 'react-router'

import { isNavItemActive, navMenuGroups, type NavItem } from '@/shared/config/nav'
import { cn } from '@/shared/lib/cn'

function MenuItem({
  item,
  active,
  onNavigate,
}: {
  item: NavItem
  active: boolean
  onNavigate?: () => void
}) {
  const Icon = item.icon

  return (
    <NavLink
      to={item.to}
      onClick={onNavigate}
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

type AppNavMenuProps = {
  onNavigate?: () => void
  className?: string
}

export function AppNavMenu({ onNavigate, className }: AppNavMenuProps) {
  const { pathname } = useLocation()

  return (
    <div
      className={cn(
        'w-[322px] rounded-[var(--border-radius-panel)] bg-white p-3 shadow-lg',
        className,
      )}
    >
      <nav className="flex flex-col gap-2">
        {navMenuGroups.map((group, groupIndex) => (
          <div key={groupIndex} className="flex flex-col gap-2">
            {groupIndex > 0 ? <div className="h-px bg-[#e4e4e7]" /> : null}
            <div className="flex flex-col gap-2">
              {group.map((item) => (
                <MenuItem
                  key={item.to}
                  item={item}
                  active={isNavItemActive(item, pathname)}
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
