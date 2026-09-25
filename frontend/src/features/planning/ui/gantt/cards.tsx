import type { ComponentType, CSSProperties, PointerEvent } from 'react'
import { Tooltip } from '@heroui/react'
import {
  RiArrowRightSLine,
  RiBus2Line,
  RiCarLine,
  RiCheckboxCircleFill,
  RiCloseCircleFill,
  RiDraggable,
  RiFlag2Fill,
  RiMapPin4Fill,
  RiRidingLine,
  RiRouterFill,
  RiTimeFill,
  RiWalkLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { AppTooltipContent } from '@/shared/ui'

import type { GanttStatus, GanttTask, GanttUnassigned } from '../../ganttTypes'
import { equipmentLabel, formatRange } from '../../lib/ganttPlacement'
import type { MapTransport } from '../../mapTypes'
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
      className="inline-flex h-5 shrink-0 items-center gap-1 px-1 text-xs leading-4 whitespace-nowrap text-foreground"
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
    <p className="flex h-4 min-w-0 items-center gap-1 px-1 text-xs leading-4 text-foreground">
      <RiRouterFill size={12} className="shrink-0" />
      <span className="truncate">{label}</span>
    </p>
  )
}

const TRANSPORT_ICON: Record<MapTransport, Icon> = {
  car: RiCarLine,
  public: RiBus2Line,
  bike: RiRidingLine,
  walking: RiWalkLine,
}

type RoadPartProps = {
  task: GanttTask
  transport: MapTransport
  /** Ширина участка, px: узкий — только значок, совсем узкий — пустой; минуты есть в раскрытой карточке. */
  width: number
  /** Карточка работ раскрыта — дорога берёт её рамку. */
  full?: boolean
  className?: string
}

/**
 * Левая часть плашки визита — дорога от выезда до начала работ. Цвет — по статусу:
 * инженер уже на адресе — дорога пройдена, серая; штриховка отличает её от работы.
 */
export function GanttRoadPart({ task, transport, width, full = false, className }: RoadPartProps) {
  const palette = STATUS_STYLE[task.status === 'working' ? 'done' : task.status]
  const ring = STATUS_STYLE[task.status].ring
  const TransportIcon = TRANSPORT_ICON[transport]
  const label = `Дорога ${task.travel} мин`
  return (
    <div
      role="img"
      aria-label={label}
      title={label}
      className={cn(
        'flex min-h-[52px] shrink-0 flex-col justify-center gap-0.5 overflow-hidden text-xs leading-4 whitespace-nowrap text-foreground/70 select-none',
        full ? 'border-2 border-r-0' : 'border-r border-dashed',
        width >= 64 ? 'px-1.5' : 'items-center',
        className,
      )}
      style={{
        borderRadius: '8px 0 0 8px',
        width,
        borderColor: full ? ring : palette.ring,
        background: `repeating-linear-gradient(135deg, ${palette.card} 0 6px, color-mix(in srgb, ${palette.tag} 45%, ${palette.card}) 6px 9px)`,
      }}
    >
      {width >= 16 ? (
        <span className="flex min-w-0 items-center gap-0.5">
          <TransportIcon size={12} className="shrink-0" />
          {width >= 64 ? <span className="truncate font-medium">{task.travel} мин</span> : null}
        </span>
      ) : null}
      {width >= 64 ? <span className="truncate">Дорога</span> : null}
    </div>
  )
}

type TaskCardProps = {
  task: GanttTask
  /** Раскрытый вид — при наведении и у заявки, которая ждёт подтверждения. */
  full?: boolean
  /** Слева стоит дорога — левые углы прямые, плашка выглядит одной. */
  joined?: boolean
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
  joined = false,
  className,
  style,
  onPointerDown,
  onPointerEnter,
  onPointerLeave,
}: TaskCardProps) {
  const palette = STATUS_STYLE[task.status]
  const cancelled = task.status === 'cancelled'
  const borderRadius = joined ? '0 8px 8px 0' : 8

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
        style={{ borderRadius, background: palette.card, ...style }}
      >
        <p className="truncate text-xs leading-4 font-semibold whitespace-nowrap text-foreground [text-overflow:clip]">
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
      className={cn('flex min-h-[52px] gap-1.5 border-2 p-1 select-none', joined && 'border-l-0 pl-1.5', className)}
      style={{ borderRadius, background: palette.card, borderColor: palette.ring, ...style }}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 flex-col">
          <p className="flex min-w-0 items-center gap-1 text-xs leading-4 font-semibold whitespace-nowrap text-foreground">
            <span className="truncate">{task.typeLabel}</span>
            <span>•</span>
            <span>{formatRange(task.start, task.end)}</span>
          </p>
          <p className="truncate text-xs leading-4 text-foreground/70">{task.address}</p>
          {task.travel > 0 ? (
            <p className="truncate text-xs leading-4 text-foreground/70">Дорога {task.travel} мин</p>
          ) : null}
        </div>
        <EquipmentLine ticket={task} />
        <div className="flex">
          <StatusTag status={task.status} />
        </div>
      </div>
      {task.status === 'assigned' || task.status === 'draft' ? (
        <RiDraggable size={16} aria-hidden className="shrink-0 self-center text-foreground" />
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
        approval ? 'bg-danger-soft' : 'bg-surface',
        selected ? 'border-2 border-[#475569] p-[4px]' : approval ? '' : 'border border-[#94a3b8] p-[5px]',
        onPointerDown && 'cursor-grab active:cursor-grabbing',
        className,
      )}
      style={{ borderRadius: 8 }}
    >
      <div className="flex min-w-0 flex-1 flex-col justify-between">
        <div className="flex min-w-0 flex-col px-1">
          <p className="flex min-w-0 items-center gap-1 text-sm leading-5 font-semibold whitespace-nowrap text-foreground">
            <span className="truncate text-foreground">{ticket.typeLabel}</span>
            <span>•</span>
            <span className={cn(approval && 'line-through')}>
              {formatRange(ticket.windowFrom, ticket.windowTo)}
            </span>
          </p>
          <p className="truncate text-xs leading-4 text-foreground">{ticket.address}</p>
        </div>
        <EquipmentLine ticket={ticket} />
        <div className="flex min-w-0">
          {approval ? (
            <button
              type="button"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={onApprove}
              className="inline-flex h-5 max-w-full cursor-pointer items-center gap-1 bg-danger-soft pr-0.5 pl-1 text-xs leading-4 text-danger-soft-foreground transition-colors hover:bg-danger-soft-hover"
              style={{ borderRadius: 4 }}
            >
              <span className="truncate">Согласовать с клиентом</span>
              <RiArrowRightSLine size={12} className="shrink-0" />
            </button>
          ) : (
            <Tooltip delay={300}>
              <Tooltip.Trigger className="inline-flex max-w-full cursor-help outline-none">
                <span
                  className="truncate bg-danger-soft px-1 text-xs leading-5 text-danger-soft-foreground"
                  style={{ borderRadius: 4 }}
                >
                  {UNASSIGNED_REASON_LABEL[ticket.reason]}
                </span>
              </Tooltip.Trigger>
              <AppTooltipContent className="max-w-[360px] text-left break-normal">
                {ticket.explanation}
              </AppTooltipContent>
            </Tooltip>
          )}
        </div>
      </div>
      <RiDraggable size={16} aria-hidden className="shrink-0 self-center text-foreground" />
    </article>
  )
}
