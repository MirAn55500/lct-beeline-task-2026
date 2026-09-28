import type { ComponentType, ReactNode } from 'react'
import { Popover, Tooltip } from '@heroui/react'
import { RiErrorWarningLine, RiQuestionLine, RiRouterLine, RiTimeLine, RiTvLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { getInitials } from '@/shared/lib'
import { AppTooltipContent } from '@/shared/ui'

import type { MapEngineer, MapTicket } from '../../mapTypes'
import { TRANSPORT_FILL_ICON, TRANSPORT_LABEL } from './transport'

type Icon = ComponentType<{ size?: number | string; className?: string }>

/** Вертикальный разделитель между пунктами строки, как Separator в макете. */
export function MetaSeparator() {
  return <span aria-hidden className="h-3.5 w-px shrink-0 bg-separator" />
}

/** Инициалы с кружком транспорта в цвете маршрута. */
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
      <span
        className="absolute top-0.5 left-0 flex size-11 items-center justify-center bg-surface-tertiary text-xs leading-5 font-medium text-foreground"
        style={{ borderRadius: 8 }}
      >
        {getInitials(engineer.name.replace(/^Бригада\s+/, ''))}
      </span>
      <span
        title={TRANSPORT_LABEL[engineer.transport]}
        className="absolute bottom-[-3px] left-[-3px] flex size-5 items-center justify-center rounded-full border-2 border-surface"
        style={{ background: muted ? '#ffffff' : engineer.color }}
      >
        <TransportIcon size={14} className={muted ? 'text-muted' : 'text-[var(--beeline-white)]'} />
      </span>
    </div>
  )
}

/** Цвет кольца загрузки — accent / warning / danger, как _ProgressCircleColors в макете. */
function loadColor(load: number) {
  if (load >= 25) return 'var(--link)'
  if (load >= 10) return '#f5a524'
  return 'var(--danger)'
}

export function LoadRing({ value, trackColor = 'var(--surface-tertiary)' }: { value: number; trackColor?: string }) {
  const radius = 7
  const length = 2 * Math.PI * radius
  return (
    <span className="flex items-center gap-1">
      <span className="text-sm leading-6 font-medium text-foreground">{value}%</span>
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
        tone === 'danger' ? 'bg-danger-soft text-danger-soft-foreground' : 'bg-surface-tertiary text-foreground',
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

/** Почему заявка у этого инженера: ссылка, полное объяснение планировщика — во всплывающем окне. */
export function ExplanationPopover({ explanation }: { explanation: string }) {
  return (
    <Popover>
      <Popover.Trigger className="inline-flex w-fit cursor-pointer items-center gap-1 text-sm leading-5 font-medium text-link outline-none hover:underline focus-visible:underline">
        <RiQuestionLine size={16} className="shrink-0" />
        Почему этот инженер
      </Popover.Trigger>
      <Popover.Content
        placement="right top"
        offset={12}
        className="w-[360px] max-w-[calc(100vw-32px)] border-0 bg-surface p-0 text-foreground outline-none"
        style={{
          borderRadius: 16,
          boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
        }}
      >
        <Popover.Dialog className="flex flex-col gap-1 p-4 outline-none" style={{ borderRadius: 16 }}>
          <Popover.Heading className="text-base leading-6 font-semibold text-foreground">
            Почему этот инженер
          </Popover.Heading>
          <p className="text-sm leading-5 text-foreground">{explanation}</p>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  )
}
