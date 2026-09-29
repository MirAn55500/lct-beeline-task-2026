import { useState } from 'react'
import { createPortal } from 'react-dom'
import { ScrollShadow } from '@heroui/react'
import {
  RiRouterLine,
  RiTimeLine,
  RiToolsFill,
  RiTvLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { pluralRu } from '@/shared/lib'
import { AppPanel } from '@/shared/ui'

import type { MapEngineer, MapTransport } from '../../mapTypes'
import { EngineerSearchFilters, filterEngineers } from '../EngineerSearchFilters'
import { EngineerAvatar, LoadRing, MetaSeparator } from './parts'

type HoverCard = { engineer: MapEngineer; top: number; left: number }

type EngineersSidebarProps = {
  engineers: MapEngineer[]
  selectedId: string | null
  hoveredId: string | null
  onSelect: (engineerId: string) => void
  onHover: (engineerId: string | null) => void
  onUnavailable?: (engineerId: string) => void
}

export function EngineersSidebar({
  engineers,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
  onUnavailable,
}: EngineersSidebarProps) {
  const [query, setQuery] = useState('')
  const [transports, setTransports] = useState<ReadonlySet<MapTransport>>(() => new Set())
  const [card, setCard] = useState<HoverCard | null>(null)

  const visible = filterEngineers(engineers, query, transports)

  const leave = () => {
    setCard(null)
    onHover(null)
  }

  // Плана на день нет — панель пустая, как в макете «work-area - map-layout».
  if (engineers.length === 0) return <AppPanel className="min-h-0 flex-1" />

  return (
    <AppPanel className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <EngineerSearchFilters
        query={query}
        onQueryChange={setQuery}
        transports={transports}
        onTransportsChange={setTransports}
        className="shrink-0 p-3"
      />

      <ScrollShadow hideScrollBar className="min-h-0 flex-1 overflow-y-auto" onScroll={leave}>
        {visible.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm leading-5 text-muted">
            Никого не нашли
          </p>
        ) : (
          <ul className="flex flex-col">
            {visible.map((engineer) => {
              const selected = engineer.id === selectedId
              const hovered = engineer.id === hoveredId && !selected
              return (
                <li key={engineer.id}>
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => {
                      setCard(null)
                      onSelect(engineer.id)
                    }}
                    onMouseEnter={(event) => {
                      onHover(engineer.id)
                      if (selected) return
                      const rect = event.currentTarget.getBoundingClientRect()
                      setCard({ engineer, top: rect.top, left: rect.right })
                    }}
                    onMouseLeave={leave}
                    className={cn(
                      'flex w-full cursor-pointer items-center gap-3 border-b border-border p-3 text-left outline-none transition-colors focus-visible:bg-surface-hover',
                      selected ? 'bg-surface-tertiary' : hovered ? 'bg-surface-hover' : 'bg-surface',
                    )}
                  >
                    <EngineerAvatar engineer={engineer} muted={selected} />
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex items-center gap-1">
                        <span className="min-w-0 flex-1 truncate text-base leading-6 font-semibold text-foreground">
                          {engineer.name}
                        </span>
                        <LoadRing
                          value={engineer.load}
                          trackColor={selected ? 'var(--surface)' : 'var(--surface-tertiary)'}
                        />
                      </span>
                      <span className="flex items-center gap-2 text-sm leading-5 font-medium text-muted">
                        <span className="flex items-center gap-0.5">
                          <RiToolsFill size={14} />
                          {engineer.qualification}
                        </span>
                        <MetaSeparator />
                        <span className="flex items-center gap-0.5">
                          <RiTimeLine size={14} />
                          {engineer.routeFrom ? `${engineer.routeFrom}-${engineer.routeTo}` : engineer.shift}
                        </span>
                      </span>
                    </span>
                  </button>
                  {selected && onUnavailable ? (
                    <button
                      type="button"
                      onClick={() => onUnavailable(engineer.id)}
                      className="w-full cursor-pointer border-b border-border bg-surface-tertiary px-3 py-2 text-left text-sm leading-5 font-medium text-foreground hover:bg-surface-hover"
                    >
                      Недоступен с…
                    </button>
                  ) : null}
                </li>
              )
            })}
          </ul>
        )}
      </ScrollShadow>

      {card ? createPortal(<EngineerHoverCard {...card} />, document.body) : null}
    </AppPanel>
  )
}

/** Продолжение строки вправо поверх карты: смена и оборудование, как во фрейме наведения. */
function EngineerHoverCard({ engineer, top, left }: HoverCard) {
  return (
    <div
      role="tooltip"
      className="pointer-events-none fixed z-50 flex h-[72px] w-[350px] flex-col justify-center gap-1 border border-border bg-surface-hover py-3 pr-3 pl-4"
      style={{ top, left, borderRadius: '0 8px 8px 0' }}
    >
      <p className="truncate text-base leading-6 font-medium text-foreground">
        Рабочая смена: {engineer.shift}
      </p>
      <p className="flex items-center gap-2 text-sm leading-5 font-medium text-muted">
        <span className="flex items-center gap-0.5">
          <RiRouterLine size={16} />
          {engineer.routers} {pluralRu(engineer.routers, ['роутер', 'роутера', 'роутеров'])}
        </span>
        <MetaSeparator />
        <span className="flex items-center gap-0.5">
          <RiTvLine size={16} />
          {engineer.boxes} {pluralRu(engineer.boxes, ['приставка', 'приставки', 'приставок'])}
        </span>
      </p>
    </div>
  )
}
