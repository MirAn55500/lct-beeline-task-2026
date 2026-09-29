import { Dropdown } from '@heroui/react'
import { RiEqualizer2Line, RiSearchLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

import type { MapEngineer, MapTransport } from '../mapTypes'
import { TRANSPORT_LABEL } from './map/transport'

const TRANSPORT_ORDER: MapTransport[] = ['car', 'public', 'bike', 'walking']

const MENU_ITEM =
  'flex h-9 cursor-pointer items-center gap-2 px-3 text-sm font-medium leading-5 text-foreground outline-none data-[focused]:bg-surface-hover'

type EngineerSearchFiltersProps = {
  query: string
  onQueryChange: (query: string) => void
  transports: ReadonlySet<MapTransport>
  onTransportsChange: (transports: ReadonlySet<MapTransport>) => void
  className?: string
}

export function filterEngineers<T extends MapEngineer>(
  engineers: T[],
  query: string,
  transports: ReadonlySet<MapTransport>,
): T[] {
  const needle = query.trim().toLowerCase()
  return engineers.filter(
    (engineer) =>
      (needle === '' || engineer.name.toLowerCase().includes(needle)) &&
      (transports.size === 0 || transports.has(engineer.transport)),
  )
}

/** Общие поиск и фильтр инженеров для карты и Ганта. */
export function EngineerSearchFilters({
  query,
  onQueryChange,
  transports,
  onTransportsChange,
  className,
}: EngineerSearchFiltersProps) {
  return (
    <div className={cn('flex min-w-0 items-center gap-2', className)}>
      <label
        className="flex h-9 min-w-0 flex-1 items-center gap-1.5 border border-border bg-surface px-3 focus-within:border-focus"
        style={{ borderRadius: 8 }}
      >
        <RiSearchLine size={16} className="shrink-0 text-muted" />
        <input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Поиск по инженерам"
          className="min-w-0 flex-1 bg-transparent text-sm leading-5 text-foreground outline-none placeholder:text-muted"
        />
      </label>

      <Dropdown>
        <Dropdown.Trigger
          aria-label="Фильтры"
          className="relative flex size-9 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-foreground outline-none transition-colors hover:bg-surface-hover data-[pressed]:bg-surface-hover"
          style={{ borderRadius: 8 }}
        >
          <RiEqualizer2Line size={16} />
          {transports.size > 0 ? (
            <span className="absolute -top-1 -right-1 size-2.5 rounded-full border-2 border-surface bg-accent" />
          ) : null}
        </Dropdown.Trigger>
        <Dropdown.Popover
          placement="bottom end"
          offset={8}
          className="w-[240px] border-0 bg-surface p-1 outline-none"
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
              onTransportsChange(
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
                className={cn(MENU_ITEM, 'data-[selected]:bg-surface-hover')}
                style={{ borderRadius: 8 }}
              >
                {TRANSPORT_LABEL[code]}
              </Dropdown.Item>
            ))}
          </Dropdown.Menu>
        </Dropdown.Popover>
      </Dropdown>
    </div>
  )
}
