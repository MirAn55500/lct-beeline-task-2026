import { RiLoader4Line } from '@remixicon/react'

/**
 * Идёт загрузка версии плана. Пока она грузится, на экране остаётся прежняя — без этой
 * плашки не видно, что открывается другая. Родителю нужен `relative`.
 */
export function PlanLoadingBadge({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <div
      role="status"
      className="pointer-events-none absolute top-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 border border-border bg-surface px-3 py-1.5 text-sm leading-5 text-muted shadow-sm"
    >
      <RiLoader4Line size={16} className="shrink-0 animate-spin" />
      Загружаем план
    </div>
  )
}
