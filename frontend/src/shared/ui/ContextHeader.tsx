import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Calendar } from '@heroui/react'
import type { CalendarDate } from '@internationalized/date'
import {
  RiAddCircleLine,
  RiArrowDownSLine,
  RiDownloadFill,
  RiFileDownloadLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { formatDayLabel } from '@/shared/lib/format'
import { AppPanel } from '@/shared/ui/AppPanel'

function ContextSelect({
  label,
  muted,
  open,
  onToggle,
  children,
}: {
  label: string
  muted?: boolean
  open: boolean
  onToggle: () => void
  children?: ReactNode
}) {
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          'flex cursor-pointer items-center gap-1 text-left text-xl font-semibold leading-7 transition-colors hover:opacity-80',
          muted || open ? 'text-[#71717a]' : 'text-foreground',
        )}
      >
        <span>{label}</span>
        <RiArrowDownSLine
          size={20}
          className={cn(
            'shrink-0 transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>
      {children}
    </div>
  )
}

type ContextRegion = {
  id: number
  name: string
}

type ContextPlan = {
  id: number
  version: number
  createdAt: string
}

function formatPlanStamp(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const day = new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date)
  const time = new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
  return `От ${day}, ${time}`
}

type ContextHeaderProps = {
  className?: string
  regions?: ContextRegion[]
  regionId?: number | null
  onRegionIdChange?: (regionId: number) => void
  date: CalendarDate
  onDateChange?: (date: CalendarDate) => void
  plannedDates?: string[]
  plans?: ContextPlan[]
  planId?: number | null
  onPlanIdChange?: (planId: number) => void
  isRegionsLoading?: boolean
  isRegionsError?: boolean
  isUploadDisabled?: boolean
  onUploadClick?: () => void
  isRecalculating?: boolean
  onRecalculate?: () => void
  /** Блок по центру шапки, например переключатель вида плана. */
  center?: ReactNode
  /** Показывать ли день недели рядом с датой; в макетах его нет. */
  showWeekday?: boolean
  /** Экспорт заявок дня; без него пункты экспорта неактивны. */
  onExport?: (format: 'csv' | 'json') => void
}

export function ContextHeader({
  className,
  regions = [],
  regionId = null,
  onRegionIdChange,
  date,
  onDateChange,
  plannedDates = [],
  plans = [],
  planId = null,
  onPlanIdChange,
  isRegionsLoading = false,
  isRegionsError = false,
  isUploadDisabled = false,
  onUploadClick,
  isRecalculating = false,
  onRecalculate,
  center,
  showWeekday = false,
  onExport,
}: ContextHeaderProps) {
  const [regionOpen, setRegionOpen] = useState(false)
  const [dateOpen, setDateOpen] = useState(false)
  const [versionOpen, setVersionOpen] = useState(false)
  const [ticketsOpen, setTicketsOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const region = regions.find((item) => item.id === regionId) ?? null
  const selectedPlan = plans.find((item) => item.id === planId) ?? plans[0] ?? null
  const plannedDateSet = useMemo(() => new Set(plannedDates), [plannedDates])

  const regionLabel = isRegionsLoading
    ? 'Регион'
    : (region?.name ?? 'Нет регионов')

  useEffect(() => {
    if (!regionOpen && !dateOpen && !versionOpen && !ticketsOpen) return

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setRegionOpen(false)
        setDateOpen(false)
        setVersionOpen(false)
        setTicketsOpen(false)
      }
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setRegionOpen(false)
        setDateOpen(false)
        setVersionOpen(false)
        setTicketsOpen(false)
      }
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [regionOpen, dateOpen, versionOpen, ticketsOpen])

  return (
    <AppPanel
      ref={rootRef}
      className={cn(
        'relative h-[60px] shrink-0 items-center px-3',
        // С центральным блоком края делят остаток поровну, чтобы центр стоял ровно посередине.
        center ? 'grid grid-cols-[1fr_auto_1fr] gap-4' : 'flex justify-between',
        className,
      )}
    >
      <div className="flex items-center gap-4 px-1">
        <ContextSelect
          label={regionLabel}
          muted={!region}
          open={regionOpen}
          onToggle={() => {
            setDateOpen(false)
            setVersionOpen(false)
            setTicketsOpen(false)
            setRegionOpen((value) => !value)
          }}
        >
          {regionOpen ? (
            <div className="absolute top-[calc(100%+12px)] left-0 z-50 w-max min-w-[193px] rounded-[var(--border-radius-panel)] bg-white p-1 shadow-lg">
              {regions.length === 0 ? (
                <p className="px-3 py-2 text-sm leading-6 text-[#71717a]">
                  {isRegionsError
                    ? 'Не удалось загрузить регионы'
                    : 'Регионов пока нет'}
                </p>
              ) : (
                <div className="flex flex-col">
                  {regions.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        onRegionIdChange?.(item.id)
                        setRegionOpen(false)
                      }}
                      className={cn(
                        'flex h-9 w-full cursor-pointer items-center rounded-lg px-3 text-sm font-medium leading-6 text-foreground transition-colors hover:bg-[#f5f5f5]',
                        item.id === region?.id && 'bg-[#f5f5f5]',
                      )}
                    >
                      {item.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </ContextSelect>

        <div className="h-7 w-px bg-[#e4e4e7]" />

        <ContextSelect
          label={formatDayLabel(date, { weekday: showWeekday })}
          open={dateOpen}
          onToggle={() => {
            setRegionOpen(false)
            setVersionOpen(false)
            setTicketsOpen(false)
            setDateOpen((value) => !value)
          }}
        >
          {dateOpen ? (
            <div
              className="absolute top-[calc(100%+12px)] left-0 z-50 w-[288px] overflow-hidden bg-white p-4 pt-0 shadow-lg"
              style={{ borderRadius: 24 }}
            >
              <Calendar
                aria-label="Дата"
                className="w-full"
                firstDayOfWeek="mon"
                value={date}
                onChange={(value) => {
                  if (!value) return
                  onDateChange?.(value)
                  setDateOpen(false)
                }}
              >
                <Calendar.Header className="px-0 pb-2 pt-4">
                  <Calendar.YearPickerTrigger className="gap-1">
                    <Calendar.YearPickerTriggerHeading className="text-sm font-medium text-foreground" />
                    <Calendar.YearPickerTriggerIndicator className="text-[#1d63ae]" />
                  </Calendar.YearPickerTrigger>
                  <Calendar.NavButton
                    slot="previous"
                    className="size-6 text-[#1d63ae] hover:bg-[#f5f5f5]"
                    style={{ borderRadius: 6 }}
                  />
                  <Calendar.NavButton
                    slot="next"
                    className="size-6 text-[#1d63ae] hover:bg-[#f5f5f5]"
                    style={{ borderRadius: 6 }}
                  />
                </Calendar.Header>
                <Calendar.Grid className="w-full">
                  <Calendar.GridHeader>
                    {(day) => (
                      <Calendar.HeaderCell className="h-10 w-9 text-sm font-medium text-[#71717a]">
                        {day}
                      </Calendar.HeaderCell>
                    )}
                  </Calendar.GridHeader>
                  <Calendar.GridBody>
                    {(cellDate) => (
                      <Calendar.Cell
                        date={cellDate}
                        className="size-9 text-sm font-medium text-foreground hover:bg-[#f5f5f5] data-[outside-month=true]:text-[#71717a] data-[selected=true]:bg-[#0485f7] data-[selected=true]:text-[#fcfcfc] data-[selected=true]:hover:bg-[#0374d9]"
                        style={{ borderRadius: 24 }}
                      >
                        {({ formattedDate, isSelected }) => (
                          <>
                            {formattedDate}
                            {plannedDateSet.has(cellDate.toString()) ? (
                              <Calendar.CellIndicator
                                className={
                                  isSelected ? 'bg-[#fcfcfc]' : 'bg-[#71717a]'
                                }
                              />
                            ) : null}
                          </>
                        )}
                      </Calendar.Cell>
                    )}
                  </Calendar.GridBody>
                </Calendar.Grid>
                <Calendar.YearPickerGrid>
                  <Calendar.YearPickerGridBody>
                    {({ year }) => <Calendar.YearPickerCell year={year} />}
                  </Calendar.YearPickerGridBody>
                </Calendar.YearPickerGrid>
              </Calendar>
            </div>
          ) : null}
        </ContextSelect>

      </div>

      {center}

      <div className="flex items-center justify-end gap-2">
        {selectedPlan ? (
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setRegionOpen(false)
                setDateOpen(false)
                setTicketsOpen(false)
                setVersionOpen((value) => !value)
              }}
              className="flex h-9 cursor-pointer items-center gap-5 border border-[#dedee0] bg-white px-3 text-sm leading-5 text-foreground transition-colors hover:bg-[#f5f5f5]"
              style={{ borderRadius: 8 }}
            >
              План №{selectedPlan.version}
              <RiArrowDownSLine
                size={16}
                className={cn('shrink-0 transition-transform', versionOpen && 'rotate-180')}
              />
            </button>
            {versionOpen ? (
              <div
                className="absolute top-[calc(100%+8px)] right-0 z-50 w-[193px] bg-white p-1 shadow-lg"
                style={{ borderRadius: 16 }}
              >
                <div className="flex flex-col">
                  {plans.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        onPlanIdChange?.(item.id)
                        setVersionOpen(false)
                      }}
                      className={cn(
                        'flex w-full cursor-pointer flex-col items-start rounded-lg px-3 py-2 text-left transition-colors hover:bg-[#f5f5f5]',
                        item.id === selectedPlan.id && 'bg-[#f5f5f5]',
                      )}
                    >
                      <span className="text-sm font-medium leading-5 text-foreground">
                        План №{item.version}
                      </span>
                      <span className="text-xs leading-5 text-[#71717a]">
                        {formatPlanStamp(item.createdAt)}
                      </span>
                    </button>
                  ))}
                  <div className="mx-2 my-1 h-px bg-[#e4e4e7]" />
                  <button
                    type="button"
                    disabled={isRecalculating || !onRecalculate}
                    onClick={() => {
                      setVersionOpen(false)
                      onRecalculate?.()
                    }}
                    className="flex h-9 w-full cursor-pointer items-center justify-center gap-2 rounded-lg px-3 text-sm font-medium text-foreground transition-colors hover:bg-[#f5f5f5] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <RiAddCircleLine size={16} className="shrink-0" />
                    {isRecalculating ? 'Считаем план' : 'Новый план'}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="relative">
          <div
            className="flex h-9 items-stretch overflow-hidden bg-[#0485f7]"
            style={{ borderRadius: 8 }}
          >
            <button
              type="button"
              disabled={isUploadDisabled}
              onClick={onUploadClick}
              className="inline-flex cursor-pointer items-center bg-[#0485f7] px-4 text-sm leading-5 font-medium text-[#fcfcfc] transition-colors hover:bg-[#0374d9] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-[#0485f7]"
            >
              Заявки
            </button>
            <span className="my-2 w-px shrink-0 bg-[#fcfcfc]/40" aria-hidden />
            <button
              type="button"
              aria-label="Действия с заявками"
              aria-expanded={ticketsOpen}
              onClick={() => {
                setRegionOpen(false)
                setDateOpen(false)
                setVersionOpen(false)
                setTicketsOpen((value) => !value)
              }}
              className={cn(
                'inline-flex w-9 cursor-pointer items-center justify-center text-[#fcfcfc] transition-colors hover:bg-[#0374d9]',
                ticketsOpen ? 'bg-[#3592f9]' : 'bg-[#0485f7]',
              )}
            >
              <RiArrowDownSLine
                size={16}
                className={cn(
                  'shrink-0 transition-transform',
                  ticketsOpen && 'rotate-180',
                )}
              />
            </button>
          </div>
          {ticketsOpen ? (
            <div
              className="absolute top-[calc(100%+8px)] right-0 z-50 w-[193px] bg-white p-1 shadow-lg"
              style={{ borderRadius: 16 }}
            >
              {[
                { label: 'Импорт csv', icon: RiFileDownloadLine, disabled: isUploadDisabled || !onUploadClick, run: onUploadClick },
                { label: 'Импорт json', icon: RiDownloadFill, disabled: isUploadDisabled || !onUploadClick, run: onUploadClick },
                null,
                { label: 'Экспорт csv', icon: RiFileDownloadLine, disabled: !onExport, run: () => onExport?.('csv') },
                { label: 'Экспорт json', icon: RiDownloadFill, disabled: !onExport, run: () => onExport?.('json') },
              ].map((item, index) =>
                item == null ? (
                  <div key={index} className="mx-2 my-1 h-px bg-[#e4e4e7]" />
                ) : (
                  <button
                    key={item.label}
                    type="button"
                    disabled={item.disabled}
                    onClick={() => {
                      setTicketsOpen(false)
                      item.run?.()
                    }}
                    className="flex h-9 w-full cursor-pointer items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-[#18181b] transition-colors hover:bg-[#f5f5f5] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
                  >
                    <item.icon size={16} className="shrink-0 text-[#71717a]" />
                    {item.label}
                  </button>
                ),
              )}
            </div>
          ) : null}
        </div>
      </div>
    </AppPanel>
  )
}
