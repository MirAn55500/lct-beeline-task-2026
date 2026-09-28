import { getInitials } from '@/shared/lib'
import { cn } from '@/shared/lib/cn'

import type { GanttEngineer } from '../../ganttTypes'
import { formatRange } from '../../lib/ganttPlacement'
import { TRANSPORT_FILL_ICON, TRANSPORT_LABEL } from '../map/transport'

/** Кольцо загрузки как в строке инженера на Ганте: 16px, тёмное по светлому. */
function LoadRing({ value }: { value: number }) {
  const radius = 6.5
  const length = 2 * Math.PI * radius
  return (
    <span className="flex shrink-0 items-center gap-1">
      <span className="text-xs leading-4 font-semibold text-foreground">{value}%</span>
      <svg width={16} height={16} viewBox="0 0 16 16" aria-hidden className="-rotate-90">
        <circle cx={8} cy={8} r={radius} fill="none" stroke="var(--surface-tertiary)" strokeWidth={3} />
        {value > 0 ? (
          <circle
            cx={8}
            cy={8}
            r={radius}
            fill="none"
            stroke="var(--foreground)"
            strokeWidth={3}
            strokeDasharray={`${(Math.min(100, value) / 100) * length} ${length}`}
          />
        ) : null}
      </svg>
    </span>
  )
}

function Summary({ engineer, badgeClassName }: { engineer: GanttEngineer; badgeClassName?: string }) {
  const TransportIcon = TRANSPORT_FILL_ICON[engineer.transport]
  return (
    <div className="flex w-[282px] shrink-0 items-center gap-2">
      <div className="relative size-10 shrink-0">
        <span
          className="flex size-10 items-center justify-center bg-surface-tertiary text-xs leading-5 font-medium text-foreground"
          style={{ borderRadius: 8 }}
        >
          {getInitials(engineer.name.replace(/^Бригада\s+/, ''))}
        </span>
        <span
          title={TRANSPORT_LABEL[engineer.transport]}
          className={cn(
            'absolute top-[26px] left-[-6px] flex size-5 items-center justify-center rounded-full bg-surface',
            badgeClassName,
          )}
        >
          <TransportIcon size={16} className="text-foreground" />
        </span>
      </div>
      <div className="flex min-w-0 flex-1 flex-col py-0.5">
        <p className="truncate text-sm leading-5 font-semibold text-foreground">{engineer.name}</p>
        <div className="flex items-center gap-2 py-0.5">
          <p className="min-w-0 flex-1 truncate text-xs leading-4 text-foreground">{engineer.qualification}</p>
          <LoadRing value={engineer.load} />
        </div>
      </div>
    </div>
  )
}

/** «Приставка 1шт, роутер 2шт» — что инженер везёт с собой. */
function inventoryLabel(engineer: GanttEngineer) {
  const parts = []
  if (engineer.boxes > 0) parts.push(`приставка ${engineer.boxes}шт`)
  if (engineer.routers > 0) parts.push(`роутер ${engineer.routers}шт`)
  if (parts.length === 0) return 'Без снаряжения'
  const text = parts.join(', ')
  return text[0]!.toUpperCase() + text.slice(1)
}

/** Строка инженера слева от ленты; при наведении раскрывается карточкой с графиком и снаряжением. */
export function EngineerCell({
  engineer,
  hovered,
  onHover,
}: {
  engineer: GanttEngineer
  hovered: boolean
  onHover: (engineerId: string | null) => void
}) {
  return (
    <div
      className="relative flex h-[60px] items-center border-b border-separator px-3 py-2"
      onPointerEnter={() => onHover(engineer.id)}
      onPointerLeave={() => onHover(null)}
    >
      <Summary engineer={engineer} />
      {hovered ? (
        <div
          className="pointer-events-none absolute top-0 left-0 z-10 flex h-[60px] items-center gap-3 border-2 border-border bg-surface-hover px-3 py-2 shadow-[0_8px_16px_rgb(15_23_42/0.08)]"
          style={{ borderRadius: 12 }}
        >
          <Summary engineer={engineer} badgeClassName="bg-surface-hover" />
          <div className="flex flex-col border-l border-border pl-3 whitespace-nowrap">
            <p className="text-sm leading-5 font-semibold text-foreground">
              График: {engineer.shifts.map(([from, to]) => formatRange(from, to)).join(', ')}
            </p>
            <p className="text-xs leading-4 text-foreground">{inventoryLabel(engineer)}</p>
          </div>
        </div>
      ) : null}
    </div>
  )
}
