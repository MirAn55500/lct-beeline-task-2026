import { ScrollShadow, Tooltip } from '@heroui/react'
import { RiAddCircleLine, RiUser3Line, RiVipCrown2Line } from '@remixicon/react'

import type { PersonnelBrigade } from '@/features/personnel/types'
import { cn } from '@/shared/lib/cn'
import { pluralRu } from '@/shared/lib/text'
import { AppPanel, AppTooltipContent } from '@/shared/ui'

function BrigadeCard({
  brigade,
  count,
  selected,
  onSelect,
}: {
  brigade: PersonnelBrigade
  count: number
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        'flex w-full cursor-pointer flex-col gap-1 border border-border text-left transition-colors',
        selected ? 'bg-surface-hover' : 'bg-surface hover:bg-surface-hover',
      )}
      style={{ borderRadius: 8, padding: '12px 16px' }}
    >
      <span className="truncate text-base font-semibold leading-6 text-foreground">
        {brigade.name}
      </span>
      <span className="flex min-w-0 items-center gap-2 text-sm font-medium leading-6 text-muted">
        {brigade.leaderShortName ? (
          <>
            <span className="flex min-w-0 items-center gap-1" title="Бригадир">
              <RiVipCrown2Line size={16} className="shrink-0" />
              <span className="truncate">{brigade.leaderShortName}</span>
            </span>
            <span aria-hidden className="h-3.5 w-px shrink-0 bg-separator" />
          </>
        ) : null}
        <span className="flex shrink-0 items-center gap-1">
          <RiUser3Line size={16} className="shrink-0" />
          {count} {pluralRu(count, ['человек', 'человека', 'человек'])}
        </span>
      </span>
    </button>
  )
}

type BrigadesPanelProps = {
  brigades: PersonnelBrigade[]
  countById: Record<number, number>
  selectedId: number | null
  isLoading?: boolean
  onSelect: (brigadeId: number) => void
}

export function BrigadesPanel({
  brigades,
  countById,
  selectedId,
  isLoading = false,
  onSelect,
}: BrigadesPanelProps) {
  return (
    <AppPanel className="flex min-h-0 flex-1 flex-col">
      <ScrollShadow
        hideScrollBar
        size={40}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
        <div className="flex flex-col gap-3 px-3 py-3">
          {brigades.length === 0 ? (
            <p className="px-2 py-3 text-sm leading-6 text-muted">
              {isLoading ? 'Загружаем бригады…' : 'Бригад пока нет'}
            </p>
          ) : (
            brigades.map((brigade) => (
              <BrigadeCard
                key={brigade.id}
                brigade={brigade}
                count={countById[brigade.id] ?? brigade.engineersCount ?? 0}
                selected={brigade.id === selectedId}
                onSelect={() => onSelect(brigade.id)}
              />
            ))
          )}
        </div>
      </ScrollShadow>

      {/* Бригада — это инженеры одного региона: новая появляется вместе с регионом */}
      <div className="shrink-0 px-3 pt-2 pb-3">
        <Tooltip delay={200}>
          <Tooltip.Trigger className="w-full cursor-not-allowed outline-none">
            <span
              aria-disabled
              className="inline-flex h-9 w-full items-center justify-center gap-2 border border-border text-sm font-medium leading-5 text-foreground opacity-50"
              style={{ borderRadius: 8 }}
            >
              <RiAddCircleLine size={16} className="shrink-0" />
              Добавить бригаду
            </span>
          </Tooltip.Trigger>
          <AppTooltipContent className="max-w-[260px] text-left break-normal">
            Бригада — это инженеры одного региона, новая появляется вместе с регионом
          </AppTooltipContent>
        </Tooltip>
      </div>
    </AppPanel>
  )
}
