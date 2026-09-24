import { ScrollShadow } from '@heroui/react'
import { RiUser3Line, RiVipCrown2Line } from '@remixicon/react'

import type { PersonnelBrigade } from '@/features/personnel/types'
import { cn } from '@/shared/lib/cn'
import { pluralRu } from '@/shared/lib/text'
import { AppPanel } from '@/shared/ui'

function BrigadeCard({
  brigade,
  count,
  leader,
  selected,
  onSelect,
}: {
  brigade: PersonnelBrigade
  count: number
  leader?: string
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        'flex w-full cursor-pointer flex-col gap-1 border border-[#dedee0] px-4 py-3 text-left transition-colors',
        selected ? 'bg-[#f5f5f5]' : 'bg-white hover:bg-[#fafafa]',
      )}
      style={{ borderRadius: 8 }}
    >
      <span className="flex min-w-0 items-center gap-1 text-base font-semibold leading-6">
        <span className="truncate text-[#18181b]">{brigade.name}</span>
        <span className="shrink-0 text-[#71717a]">•</span>
        <span className="shrink-0 text-[#71717a]">{brigade.number}</span>
      </span>
      <span className="flex min-w-0 items-center gap-2 text-sm font-medium leading-6 text-[#71717a]">
        {leader ? (
          <>
            <span className="flex min-w-0 items-center gap-1">
              <RiVipCrown2Line size={16} className="shrink-0" />
              <span className="truncate">{leader}</span>
            </span>
            <span aria-hidden className="h-2.5 w-px shrink-0 bg-[#e4e4e7]" />
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
  /** Подпись бригадира, например «Белый С.». */
  leaderById?: Record<number, string | undefined>
  selectedId: number | null
  isLoading?: boolean
  onSelect: (brigadeId: number) => void
}

export function BrigadesPanel({
  brigades,
  countById,
  leaderById,
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
        <div className="flex flex-col gap-3 p-3">
          {brigades.length === 0 ? (
            <p className="px-2 py-3 text-sm leading-6 text-[#71717a]">
              {isLoading ? 'Загружаем бригады…' : 'Бригад пока нет'}
            </p>
          ) : (
            brigades.map((brigade) => (
              <BrigadeCard
                key={brigade.id}
                brigade={brigade}
                count={countById[brigade.id] ?? brigade.engineersCount ?? 0}
                leader={leaderById?.[brigade.id]}
                selected={brigade.id === selectedId}
                onSelect={() => onSelect(brigade.id)}
              />
            ))
          )}
        </div>
      </ScrollShadow>
    </AppPanel>
  )
}
