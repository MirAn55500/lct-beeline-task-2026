import type { ComponentType } from 'react'
import {
  RiCalendarEventFill,
  RiCalendarScheduleLine,
  RiGroupLine,
  RiHome5Line,
  RiQuestionLine,
} from '@remixicon/react'

import { routes } from '@/shared/config/routes'

export type NavIcon = ComponentType<{ size?: number | string; className?: string }>

export type NavItem = {
  to: string
  label: string
  icon: NavIcon
  match?: (pathname: string) => boolean
}

export const navPrimaryItems: NavItem[] = [
  {
    to: routes.overview,
    label: 'Обзор дня',
    icon: RiHome5Line,
    match: (pathname) => pathname === routes.overview,
  },
  {
    to: routes.planGantt,
    label: 'План работ',
    icon: RiCalendarScheduleLine,
    match: (pathname) => pathname.startsWith(routes.plan),
  },
  {
    to: routes.compare,
    label: 'Сравнение планов',
    icon: RiCalendarEventFill,
  },
  {
    to: routes.personnel,
    label: 'Персонал',
    icon: RiGroupLine,
  },
]

export const navHelpItem: NavItem = {
  to: routes.help,
  label: 'Помощь',
  icon: RiQuestionLine,
}

// Меню под кнопкой бренда: разделы, черта, «Помощь» — как в макете.
export const navMenuGroups: NavItem[][] = [navPrimaryItems, [navHelpItem]]

export function isNavItemActive(item: NavItem, pathname: string) {
  return item.match ? item.match(pathname) : pathname === item.to
}
