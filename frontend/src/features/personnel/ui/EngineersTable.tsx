import { useMemo, useState, type ReactNode } from 'react'
import { Checkbox, ScrollShadow, Tooltip } from '@heroui/react'
import {
  RiDeleteBinLine,
  RiInformationLine,
  RiPencilLine,
  RiSearchLine,
  RiVipCrown2Fill,
} from '@remixicon/react'

import {
  QUALIFICATION_LABEL,
  SKILL_LABEL,
  TRANSPORT_LABEL,
  type PersonnelEngineer,
  type SkillCode,
} from '@/features/personnel/mocks'
import { cn } from '@/shared/lib/cn'
import { getInitials, pluralRu } from '@/shared/lib/text'
import { AppPanel } from '@/shared/ui'

import {
  EMPTY_ENGINEERS_FILTERS,
  EngineersFiltersPopover,
  type EngineersFiltersState,
} from './EngineersFiltersPopover'
import { TRANSPORT_ICON } from './transportIcons'

const SKILL_OPTIONS = Object.values(SKILL_LABEL)
const TRANSPORT_OPTIONS = Object.values(TRANSPORT_LABEL)
const SKILLS_TOTAL = SKILL_OPTIONS.length

// Колонки по макету: 314 / 293 / 293 / 70 при ширине панели 1046.
const GRID =
  'grid grid-cols-[minmax(0,314fr)_minmax(0,293fr)_minmax(0,293fr)_70px] items-center gap-x-3 px-5'

function RowCheckbox({
  label,
  isSelected,
  isIndeterminate,
  onChange,
}: {
  label: string
  isSelected: boolean
  isIndeterminate?: boolean
  onChange: (next: boolean) => void
}) {
  return (
    <Checkbox
      aria-label={label}
      isSelected={isSelected}
      isIndeterminate={isIndeterminate}
      onChange={onChange}
      className="shrink-0"
    >
      <Checkbox.Content>
        {/* Квадрат 16px из макета: радиус HeroUI считается от --radius (16px),
            рамка и тень берутся из полей формы — задаём явно */}
        <Checkbox.Control
          className="before:!rounded-[4px]"
          style={{
            borderRadius: 4,
            borderWidth: 1,
            borderStyle: 'solid',
            borderColor: isSelected || isIndeterminate ? 'var(--accent)' : '#dedee0',
            ['--field-background' as string]:
              isSelected || isIndeterminate ? 'var(--accent)' : '#ffffff',
            ['--field-shadow' as string]: '0 0 #0000',
          }}
        >
          {/* Своя иконка: стандартная галочка HeroUI смещена от центра */}
          <Checkbox.Indicator className="!size-2.5">
            {({ isSelected, isIndeterminate }) =>
              isIndeterminate ? (
                <svg viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
                  <line x1="2" y1="5" x2="8" y2="5" />
                </svg>
              ) : isSelected ? (
                <svg viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="1.75 5.25 4 7.5 8.25 2.75" />
                </svg>
              ) : null
            }
          </Checkbox.Indicator>
        </Checkbox.Control>
      </Checkbox.Content>
    </Checkbox>
  )
}

function IconButton({
  label,
  tone,
  children,
}: {
  label: string
  tone: 'outline' | 'danger'
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      className={cn(
        'flex size-8 shrink-0 cursor-pointer items-center justify-center transition-colors',
        tone === 'outline'
          ? 'border border-[#dedee0] bg-white text-[#18181b] hover:bg-[#f5f5f5]'
          : 'bg-[#ff383c]/15 text-[#ff383c] hover:bg-[#ff383c]/25',
      )}
      style={{ borderRadius: 8 }}
    >
      {children}
    </button>
  )
}

function SkillsCell({ skills }: { skills: SkillCode[] }) {
  if (skills.length === 0) {
    return <span className="text-sm leading-6 text-[#71717a]">—</span>
  }
  if (skills.length === SKILLS_TOTAL) {
    return <span className="truncate text-sm leading-6 text-[#18181b]">Все типы работ</span>
  }
  if (skills.length === 1) {
    return (
      <span className="truncate text-sm leading-6 text-[#18181b]">
        {SKILL_LABEL[skills[0]!]}
      </span>
    )
  }

  return (
    <span className="flex min-w-0 items-center gap-1 text-sm leading-6 text-[#18181b]">
      {skills.length} {pluralRu(skills.length, ['навык', 'навыка', 'навыков'])}
      <Tooltip delay={200}>
        <Tooltip.Trigger
          aria-label="Список навыков"
          className="inline-flex cursor-help text-[#71717a] outline-none"
        >
          <RiInformationLine size={16} />
        </Tooltip.Trigger>
        <Tooltip.Content className="max-w-[320px] text-sm leading-5 break-normal">
          <ul className="flex flex-col gap-0.5">
            {skills.map((code) => (
              <li key={code} className="whitespace-nowrap">
                {SKILL_LABEL[code]}
              </li>
            ))}
          </ul>
        </Tooltip.Content>
      </Tooltip>
    </span>
  )
}

function EngineerRow({
  engineer,
  selected,
  highlighted,
  onToggle,
}: {
  engineer: PersonnelEngineer
  selected: boolean
  highlighted: boolean
  onToggle: (next: boolean) => void
}) {
  const TransportIcon = TRANSPORT_ICON[engineer.transport]

  return (
    <div
      className={cn(
        GRID,
        'h-14 border-b border-[#e4e4e7] transition-colors duration-700',
        highlighted && 'bg-[#34c759]/[0.08]',
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <RowCheckbox
          label={`Выбрать ${engineer.name}`}
          isSelected={selected}
          onChange={onToggle}
        />
        <span
          className="relative flex size-8 shrink-0 items-center justify-center bg-[#ebebec] text-xs font-medium leading-5 text-[#18181b]"
          style={{ borderRadius: 8 }}
        >
          {getInitials(engineer.name)}
          {engineer.isLead ? (
            <span
              title="Бригадир"
              className="absolute -bottom-1 -left-1 flex size-3.5 items-center justify-center bg-white text-[#52525b]"
              style={{ borderRadius: 4 }}
            >
              <RiVipCrown2Fill size={10} />
            </span>
          ) : null}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-medium leading-6 text-[#18181b]">
            {engineer.name}
          </span>
          <span className="-mt-1 truncate text-xs font-medium leading-5 text-[#71717a]">
            {engineer.position}
          </span>
        </span>
      </div>

      <SkillsCell skills={engineer.skills} />

      <span className="flex min-w-0 items-center gap-1 text-sm leading-6 text-[#18181b]">
        <TransportIcon size={16} className="shrink-0 text-[#71717a]" />
        <span className="truncate">{TRANSPORT_LABEL[engineer.transport]}</span>
      </span>

      <div className="flex justify-end gap-1.5">
        <IconButton label={`Редактировать ${engineer.name}`} tone="outline">
          <RiPencilLine size={16} />
        </IconButton>
        <IconButton label={`Удалить ${engineer.name}`} tone="danger">
          <RiDeleteBinLine size={16} />
        </IconButton>
      </div>
    </div>
  )
}

type EngineersTableProps = {
  engineers: PersonnelEngineer[]
  /** Только что добавленные строки — подсвечиваются зелёным. */
  highlightIds?: ReadonlySet<number>
}

export function EngineersTable({ engineers, highlightIds }: EngineersTableProps) {
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<EngineersFiltersState>(EMPTY_ENGINEERS_FILTERS)
  const [selected, setSelected] = useState<Set<number>>(() => new Set())

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return engineers.filter((item) => {
      if (needle && !item.name.toLowerCase().includes(needle)) return false
      if (
        filters.qualifications.length > 0 &&
        !filters.qualifications.some((code) => QUALIFICATION_LABEL[code] === item.position)
      ) {
        return false
      }
      if (
        filters.skills.length > 0 &&
        !item.skills.some((code) => filters.skills.includes(SKILL_LABEL[code]))
      ) {
        return false
      }
      if (
        filters.transports.length > 0 &&
        !filters.transports.includes(TRANSPORT_LABEL[item.transport])
      ) {
        return false
      }
      return true
    })
  }, [engineers, query, filters])

  const selectedVisible = visible.filter((item) => selected.has(item.id)).length
  const allSelected = visible.length > 0 && selectedVisible === visible.length

  const toggle = (id: number, next: boolean) =>
    setSelected((prev) => {
      const copy = new Set(prev)
      if (next) copy.add(id)
      else copy.delete(id)
      return copy
    })

  const toggleAll = (next: boolean) =>
    setSelected((prev) => {
      const copy = new Set(prev)
      for (const item of visible) {
        if (next) copy.add(item.id)
        else copy.delete(item.id)
      }
      return copy
    })

  const selectionLabel =
    selected.size === 0
      ? 'Нет выбранных инженеров'
      : `Выбрано ${selected.size} ${pluralRu(selected.size, ['инженер', 'инженера', 'инженеров'])}`

  return (
    <AppPanel className="flex min-h-0 flex-1 flex-col overflow-hidden py-3">
      <div className="flex shrink-0 items-center gap-2 px-3">
        <label className="relative flex h-9 w-[312px] min-w-0 items-center rounded-[8px] border border-[#dedee0] bg-white px-3">
          <RiSearchLine
            size={16}
            className="pointer-events-none shrink-0 text-[#71717a]"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск по инженерам"
            className="min-w-0 flex-1 border-0 bg-transparent py-2 ps-2 text-sm leading-5 text-[#18181b] outline-none placeholder:text-[#71717a]"
          />
        </label>

        <EngineersFiltersPopover
          value={filters}
          onChange={setFilters}
          skillOptions={SKILL_OPTIONS}
          transportOptions={TRANSPORT_OPTIONS}
        />

        <span
          className={cn(
            'ms-auto truncate px-4 text-sm font-medium leading-5',
            selected.size === 0 ? 'text-[#71717a]' : 'text-[#18181b]',
          )}
        >
          {selectionLabel}
        </span>
      </div>

      <div className={cn(GRID, 'mt-4 h-10 shrink-0 bg-[#f5f5f5]')}>
        <div className="flex min-w-0 items-center gap-3">
          <RowCheckbox
            label="Выбрать всех"
            isSelected={allSelected}
            isIndeterminate={selectedVisible > 0 && !allSelected}
            onChange={toggleAll}
          />
          <span className="text-xs font-medium leading-5 text-[#71717a]">Инженер</span>
        </div>
        <span className="text-xs font-medium leading-5 text-[#71717a]">Навыки</span>
        <span className="text-xs font-medium leading-5 text-[#71717a]">Транспорт</span>
        <span />
      </div>

      <ScrollShadow
        hideScrollBar
        size={40}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
        {visible.length > 0 ? (
          visible.map((engineer) => (
            <EngineerRow
              key={engineer.id}
              engineer={engineer}
              selected={selected.has(engineer.id)}
              highlighted={highlightIds?.has(engineer.id) ?? false}
              onToggle={(next) => toggle(engineer.id, next)}
            />
          ))
        ) : (
          <p className="px-5 py-8 text-center text-sm text-[#71717a]">
            {engineers.length === 0
              ? 'В бригаде пока нет инженеров'
              : 'Нет инженеров по выбранным фильтрам'}
          </p>
        )}
      </ScrollShadow>
    </AppPanel>
  )
}
