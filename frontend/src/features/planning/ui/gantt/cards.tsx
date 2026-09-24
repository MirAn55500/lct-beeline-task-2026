import type { ComponentType, CSSProperties, PointerEvent } from 'react'
import { Tooltip } from '@heroui/react'
import {
  RiArrowRightSLine,
  RiCheckboxCircleFill,
  RiCloseCircleFill,
  RiDraggable,
  RiFlag2Fill,
  RiMapPin4Fill,
  RiRouterFill,
  RiTimeFill,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

import type { GanttStatus, GanttTask, GanttUnassigned } from '../../ganttTypes'
import { equipmentLabel, formatRange } from '../../lib/ganttPlacement'
import { UNASSIGNED_REASON_LABEL } from '../../mocks'

type Icon = ComponentType<{ size?: number | string; className?: string; style?: CSSProperties }>

/** Палитра Ganta-card из макета: фон карточки, тег статуса, иконка и рамка в раскрытом виде. */
const STATUS_STYLE: Record<
  GanttStatus,
  { label: string; icon: Icon; card: string; tag: string; iconColor: string; ring: string }
> = {
  done: {
    label: 'Завершена',
    icon: RiCheckboxCircleFill,
    card: '#f1f5f9',
    tag: '#e2e8f0',
    iconColor: '#0f172a',
    ring: '#94a3b8',
  },
  working: {
    label: 'В работе',
    icon: RiTimeFill,
    card: '#fed7aa',
    tag: '#fdba74',
    iconColor: '#431407',
    ring: '#f97316',
  },
  onWay: {
    label: 'В пути',
    icon: RiMapPin4Fill,
    card: '#fed7aa',
    tag: '#fdba74',
    iconColor: '#431407',
    ring: '#f97316',
  },
  assigned: {
    label: 'Назначена',
    icon: RiFlag2Fill,
    card: '#fef3c7',
    tag: '#fcd34d',
    iconColor: '#451a03',
    ring: '#f59e0b',
  },
  draft: {
    label: 'Не назначена',
    icon: RiFlag2Fill,
    card: '#fef3c7',
    tag: '#fcd34d',
    iconColor: '#451a03',
    ring: '#f59e0b',
  },
  cancelled: {
    label: 'Отменена',
    icon: RiCloseCircleFill,
    card: '#ffffff',
    tag: '#e2e8f0',
    iconColor: '#475569',
    ring: '#cbd5e1',
  },
}

function StatusTag({ status }: { status: GanttStatus }) {
  const style = STATUS_STYLE[status]
  const StatusIcon = style.icon
  return (
    <span
      className="inline-flex h-5 shrink-0 items-center gap-1 px-1 text-xs leading-4 whitespace-nowrap text-[#18181b]"
      style={{ borderRadius: 4, background: style.tag }}
    >
      <StatusIcon size={12} className="shrink-0" style={{ color: style.iconColor }} />
      {style.label}
    </span>
  )
}

function EquipmentLine({ ticket }: { ticket: Pick<GanttTask, 'needsRouter' | 'needsBox'> }) {
  const label = equipmentLabel(ticket)
  if (!label) return null
  return (
    <p className="flex h-4 min-w-0 items-center gap-1 px-1 text-xs leading-4 text-[#18181b]">
      <RiRouterFill size={12} className="shrink-0" />
      <span className="truncate">{label}</span>
    </p>
  )
}

type TaskCardProps = {
  task: GanttTask
  /** Раскрытый вид — при наведении и у заявки, которая ждёт подтверждения. */
  full?: boolean
  className?: string
  style?: CSSProperties
  onPointerDown?: (event: PointerEvent<HTMLElement>) => void
  onPointerEnter?: () => void
  onPointerLeave?: () => void
}

/** Визит на ленте инженера. Ширина — длительность работ, лишнее обрезается, как в макете. */
export function GanttTaskCard({
  task,
  full = false,
  className,
  style,
  onPointerDown,
  onPointerEnter,
  onPointerLeave,
}: TaskCardProps) {
  const palette = STATUS_STYLE[task.status]
  const cancelled = task.status === 'cancelled'

  if (!full) {
    return (
      <article
        data-task-id={task.id}
        data-status={task.status}
        onPointerDown={onPointerDown}
        onPointerEnter={onPointerEnter}
        onPointerLeave={onPointerLeave}
        className={cn(
          'flex h-[52px] flex-col gap-1 overflow-hidden p-1.5 select-none',
          cancelled && 'border border-[#cbd5e1] p-[5px]',
          className,
        )}
        style={{ borderRadius: 8, background: palette.card, ...style }}
      >
        <p className="truncate text-xs leading-4 font-semibold whitespace-nowrap text-[#18181b] [text-overflow:clip]">
          {task.typeLabel}
        </p>
        <div className="flex">
          <StatusTag status={task.status} />
        </div>
      </article>
    )
  }

  return (
    <article
      data-task-id={task.id}
      data-status={task.status}
      onPointerDown={onPointerDown}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      className={cn('flex min-h-[52px] gap-1.5 border-2 p-1 select-none', className)}
      style={{ borderRadius: 8, background: palette.card, borderColor: palette.ring, ...style }}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 flex-col">
          <p className="flex min-w-0 items-center gap-1 text-xs leading-4 font-semibold whitespace-nowrap text-[#18181b]">
            <span className="truncate">{task.typeLabel}</span>
            <span>•</span>
            <span>{formatRange(task.start, task.end)}</span>
          </p>
          <p className="truncate text-xs leading-4 text-[#18181b]/70">{task.address}</p>
        </div>
        <EquipmentLine ticket={task} />
        <div className="flex">
          <StatusTag status={task.status} />
        </div>
      </div>
      {task.status === 'assigned' || task.status === 'draft' ? (
        <RiDraggable size={16} aria-hidden className="shrink-0 self-center text-[#18181b]" />
      ) : null}
    </article>
  )
}

type TicketCardProps = {
  ticket: GanttUnassigned
  selected?: boolean
  className?: string
  onPointerDown?: (event: PointerEvent<HTMLElement>) => void
  /** Тег «Согласовать с клиентом» у снятой при замене заявки. */
  onApprove?: () => void
}

/** Неназначенная заявка в нижней панели и в руке при перетаскивании. */
export function GanttTicketCard({ ticket, selected = false, className, onPointerDown, onApprove }: TicketCardProps) {
  const approval = ticket.needsApproval === true
  return (
    <article
      onPointerDown={onPointerDown}
      className={cn(
        'relative flex h-24 w-[288px] shrink-0 touch-none gap-1.5 p-1.5 select-none',
        approval ? 'bg-[#ff383c]/15' : 'bg-white',
        selected ? 'border-2 border-[#475569] p-[4px]' : approval ? '' : 'border border-[#94a3b8] p-[5px]',
        onPointerDown && 'cursor-grab active:cursor-grabbing',
        className,
      )}
      style={{ borderRadius: 8 }}
    >
      <div className="flex min-w-0 flex-1 flex-col justify-between">
        <div className="flex min-w-0 flex-col px-1">
          <p className="flex min-w-0 items-center gap-1 text-sm leading-5 font-semibold whitespace-nowrap text-[#18181b]">
            <span className="truncate text-black">{ticket.typeLabel}</span>
            <span>•</span>
            <span className={cn(approval && 'line-through')}>
              {formatRange(ticket.windowFrom, ticket.windowTo)}
            </span>
          </p>
          <p className="truncate text-xs leading-4 text-[#18181b]">{ticket.address}</p>
        </div>
        <EquipmentLine ticket={ticket} />
        <div className="flex min-w-0">
          {approval ? (
            <button
              type="button"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={onApprove}
              className="inline-flex h-5 max-w-full cursor-pointer items-center gap-1 bg-[#ff383c]/15 pr-0.5 pl-1 text-xs leading-4 text-[#18181b] transition-colors hover:bg-[#ff383c]/25"
              style={{ borderRadius: 4 }}
            >
              <span className="truncate">Согласовать с клиентом</span>
              <RiArrowRightSLine size={12} className="shrink-0" />
            </button>
          ) : (
            <Tooltip delay={300}>
              <Tooltip.Trigger className="inline-flex max-w-full cursor-help outline-none">
                <span
                  className="truncate bg-[#ff383c]/15 px-1 text-xs leading-5 text-[#18181b]"
                  style={{ borderRadius: 4 }}
                >
                  {UNASSIGNED_REASON_LABEL[ticket.reason]}
                </span>
              </Tooltip.Trigger>
              <Tooltip.Content className="max-w-[360px] text-sm leading-5 break-normal">
                {ticket.explanation}
              </Tooltip.Content>
            </Tooltip>
          )}
        </div>
      </div>
      <RiDraggable size={16} aria-hidden className="shrink-0 self-center text-black" />
    </article>
  )
}
