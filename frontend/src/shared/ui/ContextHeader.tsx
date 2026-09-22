import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Calendar } from '@heroui/react'
import type { CalendarDate } from '@internationalized/date'
import { RiArrowDownSLine, RiUploadCloud2Line } from '@remixicon/react'

import {
  DEFAULT_DATE,
  DEFAULT_REGION,
  REGIONS,
  hasPlannedDate,
  type Region,
} from '@/shared/config/context'
import { cn } from '@/shared/lib/cn'
import { formatDayLabel } from '@/shared/lib/format'
import { AppPanel } from '@/shared/ui/AppPanel'

function ContextSelect({
  label,
  open,
  onToggle,
  children,
}: {
  label: string
  open: boolean
  onToggle: () => void
  children?: ReactNode
}) {
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        className="flex cursor-pointer items-center gap-1 text-left text-xl font-semibold leading-7 text-foreground transition-colors hover:opacity-80"
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

type ContextHeaderProps = {
  className?: string
  isUploadDisabled?: boolean
  onUploadClick?: () => void
}

export function ContextHeader({
  className,
  isUploadDisabled = false,
  onUploadClick,
}: ContextHeaderProps) {
  const [region, setRegion] = useState<Region>(DEFAULT_REGION)
  const [date, setDate] = useState<CalendarDate>(DEFAULT_DATE)
  const [regionOpen, setRegionOpen] = useState(false)
  const [dateOpen, setDateOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!regionOpen && !dateOpen) return

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setRegionOpen(false)
        setDateOpen(false)
      }
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setRegionOpen(false)
        setDateOpen(false)
      }
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [regionOpen, dateOpen])

  return (
    <AppPanel
      ref={rootRef}
      className={cn(
        'relative flex h-[60px] shrink-0 items-center justify-between px-3',
        className,
      )}
    >
      <div className="flex items-center gap-4 px-1">
        <ContextSelect
          label={region}
          open={regionOpen}
          onToggle={() => {
            setDateOpen(false)
            setRegionOpen((value) => !value)
          }}
        >
          {regionOpen ? (
            <div className="absolute top-[calc(100%+12px)] left-0 z-50 w-[193px] rounded-[var(--border-radius-panel)] bg-white p-1 shadow-lg">
              <div className="flex flex-col">
                {REGIONS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => {
                      setRegion(item)
                      setRegionOpen(false)
                    }}
                    className={cn(
                      'flex h-9 w-full cursor-pointer items-center rounded-lg px-3 text-sm font-medium leading-6 text-foreground transition-colors hover:bg-[#f5f5f5]',
                      item === region && 'bg-[#f5f5f5]',
                    )}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </ContextSelect>

        <div className="h-7 w-px bg-[#e4e4e7]" />

        <ContextSelect
          label={formatDayLabel(date)}
          open={dateOpen}
          onToggle={() => {
            setRegionOpen(false)
            setDateOpen((value) => !value)
          }}
        >
          {dateOpen ? (
            <div className="absolute top-[calc(100%+12px)] left-0 z-50 w-[288px] rounded-3xl bg-white p-4 pt-0 shadow-lg">
              <Calendar
                aria-label="Дата"
                className="w-full"
                firstDayOfWeek="mon"
                value={date}
                onChange={(value) => {
                  if (!value) return
                  setDate(value)
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
                  />
                  <Calendar.NavButton
                    slot="next"
                    className="size-6 text-[#1d63ae] hover:bg-[#f5f5f5]"
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
                        className="size-9 rounded-full text-sm font-medium text-foreground hover:bg-[#f5f5f5] data-[outside-month=true]:text-[#71717a] data-[selected=true]:bg-[#0485f7] data-[selected=true]:text-[#fcfcfc] data-[selected=true]:hover:bg-[#0374d9]"
                      >
                        {({ formattedDate, isSelected }) => (
                          <>
                            {formattedDate}
                            {hasPlannedDate(cellDate) ? (
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

      <div className="flex items-center gap-2">
        <button
          type="button"
          className="flex h-9 cursor-pointer items-center rounded-[var(--border-radius-button-md)] px-4 text-sm font-medium text-foreground transition-colors hover:bg-[#f5f5f5]"
        >
          Обновить план
        </button>

        <button
          type="button"
          disabled={isUploadDisabled}
          onClick={onUploadClick}
          className="flex h-9 cursor-pointer items-center gap-2 rounded-[var(--border-radius-button-md)] bg-[#0485f7] px-4 text-sm font-medium text-[#fcfcfc] transition-colors hover:bg-[#0374d9] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-[#0485f7]"
        >
          <RiUploadCloud2Line size={16} className="shrink-0" />
          Загрузить заявки
        </button>
      </div>
    </AppPanel>
  )
}
