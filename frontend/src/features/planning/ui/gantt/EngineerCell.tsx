import type { GanttEngineer } from '../../ganttTypes'
import { formatRange } from '../../lib/ganttPlacement'
import { EngineerSummary } from '../map/parts'

function Summary({ engineer, className }: { engineer: GanttEngineer; className: string }) {
  return (
    <EngineerSummary engineer={engineer} className={className} />
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
      <Summary engineer={engineer} className="min-w-0 flex-1" />
      {hovered ? (
        <div
          className="pointer-events-none absolute top-0 left-0 z-10 flex h-[60px] items-center gap-3 border-2 border-border bg-surface-hover px-3 py-2 shadow-[0_8px_16px_rgb(15_23_42/0.08)]"
          style={{ borderRadius: 12 }}
        >
          <Summary
            engineer={engineer}
            className="w-[282px] shrink-0 min-[1440px]:w-[322px]"
          />
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
