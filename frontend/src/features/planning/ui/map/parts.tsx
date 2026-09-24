import type { ComponentType, ReactNode } from 'react'
import { Tooltip } from '@heroui/react'
import { RiErrorWarningLine, RiRouterLine, RiTimeLine, RiTvLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { getInitials } from '@/shared/lib'
import { AppTooltipContent } from '@/shared/ui'

import type { MapEngineer, MapTicket } from '../../mapTypes'
import { TRANSPORT_FILL_ICON, TRANSPORT_LABEL } from './transport'

type Icon = ComponentType<{ size?: number | string; className?: string }>

/** Вертикальный разделитель между пунктами строки, как Separator в макете. */
export function MetaSeparator() {
  return <span aria-hidden className="h-3.5 w-px shrink-0 bg-[#e4e4e7]" />
}

/** Фото или инициалы с кружком транспорта в цвете маршрута. */
export function EngineerAvatar({
  engineer,
  muted = false,
}: {
  engineer: MapEngineer
  /** У выбранного инженера кружок белый с серой иконкой. */
  muted?: boolean
}) {
  const TransportIcon = TRANSPORT_FILL_ICON[engineer.transport]
  return (
    <div className="relative h-12 w-11 shrink-0">
      {engineer.avatarUrl ? (
        <img
          src={engineer.avatarUrl}
          alt=""
          className="absolute top-0.5 left-0 size-11 object-cover"
          style={{ borderRadius: 4 }}
        />
      ) : (
        <span
          className="absolute top-0.5 left-0 flex size-11 items-center justify-center bg-[#ebebec] text-xs leading-5 font-medium text-[#18181b]"
          style={{ borderRadius: 8 }}
        >
          {getInitials(engineer.name.replace(/^Бригада\s+/, ''))}
        </span>
      )}
      <span
        title={TRANSPORT_LABEL[engineer.transport]}
        className="absolute bottom-[-3px] left-[-3px] flex size-5 items-center justify-center rounded-full border-2 border-white"
        style={{ background: muted ? '#ffffff' : engineer.color }}
      >
        <TransportIcon size={14} className={muted ? 'text-[#71717a]' : 'text-[#fcfcfc]'} />
      </span>
    </div>
  )
}

/** Цвет кольца загрузки — accent / warning / danger, как _ProgressCircleColors в макете. */
function loadColor(load: number) {
  if (load >= 25) return '#0485f7'
  if (load >= 10) return '#f5a524'
  return '#ff383c'
}

export function LoadRing({ value, trackColor = '#ebebec' }: { value: number; trackColor?: string }) {
  const radius = 7
  const length = 2 * Math.PI * radius
  return (
    <span className="flex items-center gap-1">
      <span className="text-sm leading-6 font-medium text-[#18181b]">{value}%</span>
      <svg width={20} height={20} viewBox="0 0 20 20" aria-hidden className="-rotate-90">
        <circle cx={10} cy={10} r={radius} fill="none" stroke={trackColor} strokeWidth={2} />
        <circle
          cx={10}
          cy={10}
          r={radius}
          fill="none"
          stroke={loadColor(value)}
          strokeWidth={2}
          strokeLinecap="round"
          strokeDasharray={`${(Math.min(100, value) / 100) * length} ${length}`}
        />
      </svg>
    </span>
  )
}

export function Tag({
  icon: TagIcon,
  children,
  tone = 'default',
  title,
}: {
  icon: Icon
  children?: ReactNode
  tone?: 'default' | 'danger'
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex h-5 shrink-0 items-center gap-1 px-1 text-xs leading-5 font-medium',
        tone === 'danger' ? 'bg-[#ff383c]/15 text-[#a43532]' : 'bg-[#ebebec] text-[#18181b]',
      )}
      style={{ borderRadius: 4 }}
    >
      <TagIcon size={12} className="shrink-0" />
      {children}
    </span>
  )
}

/** Окно визита и нужное оборудование — теги под заявкой. */
export function TicketTags({ ticket }: { ticket: MapTicket }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Tag icon={RiTimeLine}>{ticket.window}</Tag>
      {ticket.needsRouter ? (
        <span title="Нужен роутер">
          <Tag icon={RiRouterLine} />
        </span>
      ) : null}
      {ticket.needsBox ? (
        <span title="Нужна приставка">
          <Tag icon={RiTvLine} />
        </span>
      ) : null}
    </div>
  )
}

/** Причина неназначения: короткая подпись, полное объяснение планировщика — во всплывашке. */
export function ReasonTag({ label, explanation }: { label: string; explanation: string }) {
  return (
    <Tooltip delay={300}>
      <Tooltip.Trigger className="inline-flex max-w-full cursor-help outline-none">
        <Tag icon={RiErrorWarningLine} tone="danger">
          <span className="truncate">{label}</span>
        </Tag>
      </Tooltip.Trigger>
      <AppTooltipContent className="max-w-[360px] text-left break-normal">
        {explanation}
      </AppTooltipContent>
    </Tooltip>
  )
}
