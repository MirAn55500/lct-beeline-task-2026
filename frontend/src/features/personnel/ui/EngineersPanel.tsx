import { Avatar, ScrollShadow } from '@heroui/react'
import {
  RiArrowRightSLine,
  RiBus2Fill,
  RiCarFill,
  RiRidingFill,
  RiToolsFill,
} from '@remixicon/react'
import { Link } from 'react-router'
import type { ComponentType } from 'react'

import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'

type TransportKind = 'public' | 'bike' | 'car'

type EngineerPreview = {
  id: string
  name: string
  transport: TransportKind
  transportLabel: string
  skill: string
}

const TRANSPORT_ICON: Record<
  TransportKind,
  ComponentType<{ size?: number | string; className?: string }>
> = {
  public: RiBus2Fill,
  bike: RiRidingFill,
  car: RiCarFill,
}

const ENGINEERS: EngineerPreview[] = [
  {
    id: '1',
    name: 'Алексеев Александр',
    transport: 'public',
    transportLabel: 'Общ. транспорт',
    skill: 'Мастер',
  },
  {
    id: '2',
    name: 'Анна Смирнова',
    transport: 'bike',
    transportLabel: 'Велосипед',
    skill: 'Бывалый',
  },
  {
    id: '3',
    name: 'Павел Козлов',
    transport: 'car',
    transportLabel: 'Машина',
    skill: 'Бывалый',
  },
  {
    id: '4',
    name: 'Иван Петров',
    transport: 'public',
    transportLabel: 'Общ. транспорт',
    skill: 'Новичек',
  },
  {
    id: '5',
    name: 'Олег Смирнов',
    transport: 'public',
    transportLabel: 'Общ. транспорт',
    skill: 'Новичек',
  },
  {
    id: '6',
    name: 'Мария Волкова',
    transport: 'bike',
    transportLabel: 'Велосипед',
    skill: 'Мастер',
  },
  {
    id: '7',
    name: 'Дмитрий Орлов',
    transport: 'car',
    transportLabel: 'Машина',
    skill: 'Бывалый',
  },
  {
    id: '8',
    name: 'Елена Кузнецова',
    transport: 'public',
    transportLabel: 'Общ. транспорт',
    skill: 'Новичек',
  },
]

function getInitials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('')
}

function EngineerCard({ engineer }: { engineer: EngineerPreview }) {
  const TransportIcon = TRANSPORT_ICON[engineer.transport]

  return (
    <div className="flex items-center gap-4 border-b border-[#dedee0] px-5 py-3">
      <Avatar className="size-[52px] shrink-0 !rounded-lg">
        <Avatar.Fallback className="!rounded-lg bg-[#ebebec] text-xs font-medium text-foreground">
          {getInitials(engineer.name)}
        </Avatar.Fallback>
      </Avatar>

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="truncate text-base font-semibold leading-6 text-foreground">
          {engineer.name}
        </p>
        <div className="flex min-w-0 items-center gap-2 text-sm font-medium leading-6 text-[#71717a]">
          <span className="flex min-w-0 items-center gap-1">
            <TransportIcon size={16} className="shrink-0" />
            <span className="truncate">{engineer.transportLabel}</span>
          </span>
          <span className="h-2.5 w-px shrink-0 bg-[#e4e4e7]" />
          <span className="flex min-w-0 items-center gap-1">
            <RiToolsFill size={16} className="shrink-0" />
            <span className="truncate">{engineer.skill}</span>
          </span>
        </div>
      </div>
    </div>
  )
}

type EngineersPanelProps = {
  className?: string
  engineers?: EngineerPreview[]
}

export function EngineersPanel({
  className,
  engineers = ENGINEERS,
}: EngineersPanelProps) {
  const count = engineers.length

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
      <div className="flex shrink-0 flex-col gap-1 px-5 pb-2 pt-5">
        <h2 className="text-xl font-semibold leading-7 text-foreground">
          {count} инженеров
        </h2>
        <p className="text-sm leading-6 text-[#71717a]">
          Работает сегодня в рамках выбранного региона
        </p>
      </div>

      <ScrollShadow
        hideScrollBar
        size={80}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
        <div>
          {engineers.map((engineer) => (
            <EngineerCard key={engineer.id} engineer={engineer} />
          ))}
        </div>
      </ScrollShadow>

      <div className="shrink-0 px-5 pb-5 pt-2">
        <Link
          to={routes.personnel}
          className="flex h-9 w-full cursor-pointer items-center justify-center gap-2 rounded-[var(--border-radius-button-md)] border border-[#dedee0] text-sm font-medium text-foreground transition-colors hover:bg-[#f5f5f5]"
        >
          Перейти к инженерам
          <RiArrowRightSLine size={16} className="shrink-0" />
        </Link>
      </div>
    </div>
  )
}
