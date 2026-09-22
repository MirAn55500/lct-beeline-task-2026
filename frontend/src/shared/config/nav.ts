import type { ComponentType } from 'react'
import {
  RiCalendarScheduleLine,
  RiGroupLine,
  RiHome5Line,
  RiQuestionLine,
  RiSettings4Line,
} from '@remixicon/react'

export type NavIcon = ComponentType<{ size?: number | string; className?: string }>

export type NavItem = {
  to: string
  label: string
  icon: NavIcon
  match?: (pathname: string) => boolean
}

export const navPrimaryItems: NavItem[] = [
  {
    to: '/layouts/home',
    label: 'Обзор дня',
    icon: RiHome5Line,
    match: (pathname) => pathname === '/layouts/home',
  },
  {
    to: '/layouts/gantt',
    label: 'План работ',
    icon: RiCalendarScheduleLine,
    match: (pathname) =>
      pathname.startsWith('/layouts/gantt') || pathname.startsWith('/layouts/map'),
  },
  {
    to: '/layouts/personnel',
    label: 'Персонал',
    icon: RiGroupLine,
  },
  {
    to: '/layouts/config',
    label: 'Конфигурация',
    icon: RiSettings4Line,
  },
]

export const navHelpItem: NavItem = {
  to: '/layouts/help',
  label: 'Помощь',
  icon: RiQuestionLine,
}

export const navMenuGroups: NavItem[][] = [
  navPrimaryItems.slice(0, 2),
  navPrimaryItems.slice(2),
  [navHelpItem],
]

export function isNavItemActive(item: NavItem, pathname: string) {
  return item.match ? item.match(pathname) : pathname === item.to
}
