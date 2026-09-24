import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Dropdown, ScrollShadow } from '@heroui/react'
import {
  RiEqualizer2Line,
  RiRouterLine,
  RiSearchLine,
  RiTimeLine,
  RiToolsFill,
  RiTvLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { pluralRu } from '@/shared/lib'
import { AppPanel } from '@/shared/ui'

import type { MapEngineer, MapTransport } from '../../mapTypes'
import { EngineerAvatar, LoadRing, MetaSeparator } from './parts'
import { TRANSPORT_LABEL } from './transport'

const TRANSPORT_ORDER: MapTransport[] = ['car', 'public', 'bike', 'walking']

const MENU_ITEM =
  'flex h-9 cursor-pointer items-center gap-2 px-3 text-sm font-medium leading-5 text-[#18181b] outline-none data-[focused]:bg-[#f5f5f5]'

type HoverCard = { engineer: MapEngineer; top: number; left: number }

type EngineersSidebarProps = {
  engineers: MapEngineer[]
  selectedId: string | null
  hoveredId: string | null
  onSelect: (engineerId: string) => void
  onHover: (engineerId: string | null) => void
}

export function EngineersSidebar({
  engineers,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
}: EngineersSidebarProps) {
  const [query, setQuery] = useState('')
  const [transports, setTransports] = useState<ReadonlySet<MapTransport>>(() => new Set())
  const [card, setCard] = useState<HoverCard | null>(null)

  const needle = query.trim().toLowerCase()
  const visible = engineers.filter(
    (engineer) =>
      (needle === '' || engineer.name.toLowerCase().includes(needle)) &&
      (transports.size === 0 || transports.has(engineer.transport)),
  )

  const leave = () => {
    setCard(null)
    onHover(null)
  }

  return (
    <AppPanel className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 p-3">
        <label
          className="flex h-9 min-w-0 flex-1 items-center gap-1.5 border border-[#dedee0] bg-white px-3 focus-within:border-[#0485f7]"
          style={{ borderRadius: 8 }}
        >
          <RiSearchLine size={16} className="shrink-0 text-[#71717a]" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск по инженерам"
            className="min-w-0 flex-1 bg-transparent text-sm leading-5 text-[#18181b] outline-none placeholder:text-[#71717a]"
          />
        </label>

        <Dropdown>
          <Dropdown.Trigger
            aria-label="Фильтры"
            className={cn(
              'relative flex size-9 shrink-0 cursor-pointer items-center justify-center border border-[#dedee0] bg-white text-[#18181b] outline-none transition-colors hover:bg-[#f5f5f5] data-[pressed]:bg-[#f5f5f5]',
            )}
            style={{ borderRadius: 8 }}
          >
            <RiEqualizer2Line size={16} />
            {transports.size > 0 ? (
              <span className="absolute -top-1 -right-1 size-2.5 rounded-full border-2 border-white bg-[#0485f7]" />
            ) : null}
          </Dropdown.Trigger>
          <Dropdown.Popover
            placement="bottom end"
            offset={8}
            className="w-[240px] border-0 bg-white p-1 outline-none"
            style={{
              borderRadius: 12,
              boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
            }}
          >
            <Dropdown.Menu
              aria-label="Транспорт"
              selectionMode="multiple"
              selectedKeys={transports}
              onSelectionChange={(keys) =>
                setTransports(
                  keys === 'all' ? new Set(TRANSPORT_ORDER) : new Set(keys as Set<MapTransport>),
                )
              }
              className="flex flex-col outline-none"
            >
              {TRANSPORT_ORDER.map((code) => (
                <Dropdown.Item
                  key={code}
                  id={code}
                  textValue={TRANSPORT_LABEL[code]}
                  className={cn(MENU_ITEM, 'data-[selected]:bg-[#f5f5f5]')}
                  style={{ borderRadius: 8 }}
                >
                  {TRANSPORT_LABEL[code]}
                </Dropdown.Item>
              ))}
            </Dropdown.Menu>
          </Dropdown.Popover>
        </Dropdown>
      </div>

      <ScrollShadow hideScrollBar className="min-h-0 flex-1 overflow-y-auto" onScroll={leave}>
        {visible.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm leading-5 text-[#71717a]">
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
                      'flex w-full cursor-pointer items-center gap-3 border-b border-[#dedee0] p-3 text-left outline-none transition-colors focus-visible:bg-[#f8fafc]',
                      selected ? 'bg-[#efeff0]' : hovered ? 'bg-[#f8fafc]' : 'bg-white',
                    )}
                  >
                    <EngineerAvatar engineer={engineer} muted={selected} />
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex items-center gap-1">
                        <span className="min-w-0 flex-1 truncate text-base leading-6 font-semibold text-[#18181b]">
                          {engineer.name}
                        </span>
                        <LoadRing value={engineer.load} trackColor={selected ? '#ffffff' : '#ebebec'} />
                      </span>
                      <span className="flex items-center gap-2 text-sm leading-5 font-medium text-[#71717a]">
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
      className="pointer-events-none fixed z-50 flex h-[72px] w-[350px] flex-col justify-center gap-1 border border-[#e2e8f0] bg-[#f8fafc] py-3 pr-3 pl-4"
      style={{ top, left, borderRadius: '0 8px 8px 0' }}
    >
      <p className="truncate text-base leading-6 font-medium text-[#18181b]">
        Рабочая смена: {engineer.shift}
      </p>
      <p className="flex items-center gap-2 text-sm leading-5 font-medium text-[#71717a]">
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
