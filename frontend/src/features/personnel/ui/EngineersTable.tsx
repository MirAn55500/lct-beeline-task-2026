import { useMemo, useState, type ReactNode } from 'react'
import { Checkbox, ScrollShadow, Tooltip } from '@heroui/react'
import {
  RiDeleteBinLine,
  RiInformationLine,
  RiPencilLine,
  RiSearchLine,
} from '@remixicon/react'

import { useDeleteEngineerMutation } from '@/features/personnel/api'
import {
  QUALIFICATION_OPTIONS,
  SKILL_LABEL,
  TRANSPORT_LABEL,
  type PersonnelEngineer,
  type SkillCode,
} from '@/features/personnel/mocks'
import { cn } from '@/shared/lib/cn'
import { getInitials, pluralRu } from '@/shared/lib/text'
import { AppPanel, AppTooltipContent } from '@/shared/ui'

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
        <Checkbox.Control
          className="before:!rounded-[4px]"
          style={{
            borderRadius: 4,
            borderWidth: 1,
            borderStyle: 'solid',
            borderColor: isSelected || isIndeterminate ? 'var(--accent)' : 'var(--field-border)',
            ['--field-background' as string]:
              isSelected || isIndeterminate ? 'var(--accent)' : 'var(--field-background)',
            ['--field-shadow' as string]: '0 0 #0000',
          }}
        >
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
  disabled,
  onClick,
  children,
}: {
  label: string
  tone: 'outline' | 'danger'
  disabled?: boolean
  onClick?: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation()
        onClick?.()
      }}
      className={cn(
        'flex size-8 shrink-0 cursor-pointer items-center justify-center transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        tone === 'outline'
          ? 'border border-border bg-surface text-foreground hover:bg-surface-hover'
          : 'bg-danger-soft text-danger hover:bg-danger-soft-hover',
      )}
      style={{ borderRadius: 8 }}
    >
      {children}
    </button>
  )
}

function SkillsCell({ skills }: { skills: SkillCode[] }) {
  const known = skills.filter((code): code is SkillCode => code in SKILL_LABEL)
  if (known.length === 0) {
    return <span className="text-sm leading-6 text-muted">—</span>
  }
  if (known.length === SKILLS_TOTAL) {
    return <span className="truncate text-sm leading-6 text-foreground">Все типы работ</span>
  }
  if (known.length === 1) {
    return (
      <span className="truncate text-sm leading-6 text-foreground">
        {SKILL_LABEL[known[0]!]}
      </span>
    )
  }

  return (
    <span className="flex min-w-0 items-center gap-1 text-sm leading-6 text-foreground">
      {known.length} {pluralRu(known.length, ['навык', 'навыка', 'навыков'])}
      <Tooltip delay={200}>
        <Tooltip.Trigger
          aria-label="Список навыков"
          className="inline-flex cursor-help text-muted outline-none"
          onClick={(event) => event.stopPropagation()}
        >
          <RiInformationLine size={16} />
        </Tooltip.Trigger>
        <AppTooltipContent className="max-w-[320px] text-left break-normal">
          <ul className="flex flex-col gap-0.5">
            {known.map((code) => (
              <li key={code} className="whitespace-nowrap">
                {SKILL_LABEL[code]}
              </li>
            ))}
          </ul>
        </AppTooltipContent>
      </Tooltip>
    </span>
  )
}

function EngineerRow({
  engineer,
  checked,
  active,
  highlighted,
  deleting,
  onToggle,
  onOpen,
  onDelete,
}: {
  engineer: PersonnelEngineer
  checked: boolean
  active: boolean
  highlighted: boolean
  deleting?: boolean
  onToggle: (next: boolean) => void
  onOpen: () => void
  onDelete: () => void
}) {
  const TransportIcon = TRANSPORT_ICON[engineer.transport]

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen()
        }
      }}
      className={cn(
        GRID,
        'h-14 cursor-pointer border-b border-separator transition-colors duration-700',
        active && 'bg-surface-hover',
        highlighted && !active && 'bg-[#34c759]/[0.08]',
        !active && !highlighted && 'hover:bg-surface-hover',
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <span onClick={(event) => event.stopPropagation()}>
          <RowCheckbox
            label={`Выбрать ${engineer.name}`}
            isSelected={checked}
            onChange={onToggle}
          />
        </span>
        <span
          className="flex size-8 shrink-0 items-center justify-center bg-surface-tertiary text-xs font-medium leading-5 text-foreground"
          style={{ borderRadius: 999 }}
        >
          {getInitials(engineer.name)}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-medium leading-5 text-foreground">
            {engineer.name}
          </span>
          {engineer.position ? (
            <span className="truncate text-xs leading-4 text-muted">
              {engineer.position}
            </span>
          ) : null}
        </span>
      </div>

      <SkillsCell skills={engineer.skills} />

      <span className="flex min-w-0 items-center gap-1 text-sm leading-6 text-foreground">
        {TransportIcon ? (
          <TransportIcon size={16} className="shrink-0 text-muted" />
        ) : null}
        <span className="truncate">
          {TRANSPORT_LABEL[engineer.transport] ?? engineer.transport}
        </span>
      </span>

      <div className="flex justify-end gap-1.5">
        <IconButton label={`Редактировать ${engineer.name}`} tone="outline" onClick={onOpen}>
          <RiPencilLine size={16} />
        </IconButton>
        <IconButton
          label={`Удалить ${engineer.name}`}
          tone="danger"
          disabled={deleting}
          onClick={onDelete}
        >
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
  isLoading?: boolean
  /** Открытая карточка инженера. */
  activeId?: number | null
  onOpenEngineer?: (engineer: PersonnelEngineer) => void
}

export function EngineersTable({
  engineers,
  highlightIds,
  isLoading = false,
  activeId = null,
  onOpenEngineer,
}: EngineersTableProps) {
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<EngineersFiltersState>(EMPTY_ENGINEERS_FILTERS)
  const [selected, setSelected] = useState<Set<number>>(() => new Set())
  const [deleteEngineer, { isLoading: isDeleting }] = useDeleteEngineerMutation()
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return engineers.filter((item) => {
      if (needle && !item.name.toLowerCase().includes(needle)) return false
      if (
        filters.qualifications.length > 0 &&
        !(item.position && filters.qualifications.includes(item.position))
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

  const handleDelete = async (id: number) => {
    setDeletingId(id)
    try {
      await deleteEngineer(id).unwrap()
      setSelected((prev) => {
        const copy = new Set(prev)
        copy.delete(id)
        return copy
      })
    } catch {
      // Оставляем строку; RTK Query не инвалидирует кэш при ошибке.
    } finally {
      setDeletingId(null)
    }
  }

  const selectionLabel =
    selected.size === 0
      ? 'Нет выбранных инженеров'
      : `Выбрано ${selected.size} ${pluralRu(selected.size, ['инженер', 'инженера', 'инженеров'])}`

  return (
    <AppPanel className="flex min-h-0 flex-1 flex-col overflow-hidden py-3">
      <div className="flex shrink-0 items-center gap-2 px-3">
        <label className="relative flex h-9 w-[312px] min-w-0 items-center rounded-[8px] border border-border bg-surface px-3">
          <RiSearchLine
            size={16}
            className="pointer-events-none shrink-0 text-muted"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск по инженерам"
            className="min-w-0 flex-1 border-0 bg-transparent py-2 ps-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted"
          />
        </label>

        <EngineersFiltersPopover
          value={filters}
          onChange={setFilters}
          qualificationOptions={QUALIFICATION_OPTIONS}
          skillOptions={SKILL_OPTIONS}
          transportOptions={TRANSPORT_OPTIONS}
        />

        <span
          className={cn(
            'ms-auto truncate px-4 text-sm font-medium leading-5',
            selected.size === 0 ? 'text-muted' : 'text-foreground',
          )}
        >
          {selectionLabel}
        </span>
      </div>

      <div className={cn(GRID, 'mt-4 h-10 shrink-0 bg-surface-hover')}>
        <div className="flex min-w-0 items-center gap-3">
          <RowCheckbox
            label="Выбрать всех"
            isSelected={allSelected}
            isIndeterminate={selectedVisible > 0 && !allSelected}
            onChange={toggleAll}
          />
          <span className="text-xs font-medium leading-5 text-muted">Инженер</span>
        </div>
        <span className="text-xs font-medium leading-5 text-muted">Навыки</span>
        <span className="text-xs font-medium leading-5 text-muted">Транспорт</span>
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
              checked={selected.has(engineer.id)}
              active={activeId === engineer.id}
              highlighted={highlightIds?.has(engineer.id) ?? false}
              deleting={isDeleting && deletingId === engineer.id}
              onToggle={(next) => toggle(engineer.id, next)}
              onOpen={() => onOpenEngineer?.(engineer)}
              onDelete={() => void handleDelete(engineer.id)}
            />
          ))
        ) : (
          <p className="px-5 py-8 text-center text-sm text-muted">
            {isLoading
              ? 'Загружаем инженеров…'
              : engineers.length === 0
                ? 'В бригаде пока нет инженеров'
                : 'Нет инженеров по выбранным фильтрам'}
          </p>
        )}
      </ScrollShadow>
    </AppPanel>
  )
}
