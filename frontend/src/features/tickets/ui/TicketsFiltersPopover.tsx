import { useEffect, useState } from 'react'
import {
  Label,
  ListBox,
  Popover,
  Select,
  TimeField,
} from '@heroui/react'
import { Time } from '@internationalized/date'
import {
  RiArrowDownSLine,
  RiCloseLine,
  RiEqualizer2Line,
  RiTimeLine,
} from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

export const WORK_TYPE_OPTIONS = [
  'Аварийные работы',
  'Подключение',
  'Ремонт',
  'Дозаказ',
] as const

export const REASON_OPTIONS = [
  'Нет нужного навыка',
  'Нет нужного снаряжения',
  'Нет рабочего времени',
  'Конфликт времени',
  'Нет инженера в регионе',
] as const

export type TicketsFiltersState = {
  workTypes: string[]
  reasons: string[]
  timeFrom: string | null
  timeTo: string | null
}

export const EMPTY_TICKETS_FILTERS: TicketsFiltersState = {
  workTypes: [],
  reasons: [],
  timeFrom: null,
  timeTo: null,
}

function parseTime(value: string | null): Time | null {
  if (!value) return null
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim())
  if (!match) return null
  const hour = Number(match[1])
  const minute = Number(match[2])
  if (hour > 23 || minute > 59) return null
  return new Time(hour, minute)
}

function formatTime(value: Time | null): string | null {
  if (!value) return null
  return `${String(value.hour).padStart(2, '0')}:${String(value.minute).padStart(2, '0')}`
}

function timeToMinutes(value: string) {
  const [h, m] = value.split(':').map(Number)
  return h! * 60 + m!
}

/** Окно заявки «10:00 - 12:00» пересекается с фильтром [from, to]. */
export function ticketMatchesTimeWindow(
  window: string,
  timeFrom: string | null,
  timeTo: string | null,
) {
  if (!timeFrom && !timeTo) return true
  const match = /^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$/.exec(window.trim())
  if (!match) return true
  const start = timeToMinutes(match[1]!)
  const end = timeToMinutes(match[2]!)
  const from = timeFrom ? timeToMinutes(timeFrom) : 0
  const to = timeTo ? timeToMinutes(timeTo) : 24 * 60
  return start < to && end > from
}

function FilterChip({
  label,
  onRemove,
}: {
  label: string
  onRemove: () => void
}) {
  return (
    <span
      className="inline-flex h-5 max-w-full items-center gap-1 text-xs font-medium leading-5 text-[#18181b]"
      style={{
        borderRadius: 4,
        backgroundColor: '#ebebec',
        padding: '2px 4px',
      }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <span className="truncate">{label}</span>
      <span
        role="button"
        tabIndex={-1}
        aria-label={`Убрать ${label}`}
        className="inline-flex size-3 shrink-0 cursor-pointer items-center justify-center text-[#71717a] hover:text-[#18181b]"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          onRemove()
        }}
      >
        <RiCloseLine size={12} />
      </span>
    </span>
  )
}

function MultiFilterSelect({
  label,
  placeholder,
  options,
  value,
  onChange,
}: {
  label: string
  placeholder: string
  options: readonly string[]
  value: string[]
  onChange: (next: string[]) => void
}) {
  return (
    <Select
      className="w-full"
      placeholder={placeholder}
      selectionMode="multiple"
      value={value}
      onChange={(keys) => onChange(keys as string[])}
    >
      <Label className="mb-1 text-sm font-medium leading-6 text-[#18181b]">
        {label}
      </Label>
      <Select.Trigger
        className={cn(
          'flex min-h-9 w-full items-center justify-between gap-2 border border-[#dedee0] bg-white text-left shadow-none outline-none',
          'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-[#0485f7]',
        )}
        style={{ borderRadius: 8, padding: '8px 12px' }}
      >
        <Select.Value className="min-w-0 flex-1">
          {({ defaultChildren, isPlaceholder, state }) => {
            if (isPlaceholder || state.selectedItems.length === 0) {
              return (
                <span className="text-sm leading-5 text-[#71717a]">
                  {defaultChildren}
                </span>
              )
            }

            return (
              <span className="flex flex-wrap gap-1.5">
                {state.selectedItems.map((item) => {
                  const id = String(item.key)
                  return (
                    <FilterChip
                      key={id}
                      label={item.textValue || id}
                      onRemove={() =>
                        onChange(value.filter((entry) => entry !== id))
                      }
                    />
                  )
                })}
              </span>
            )
          }}
        </Select.Value>
        <Select.Indicator className="shrink-0 text-[#71717a]">
          <RiArrowDownSLine size={16} />
        </Select.Indicator>
      </Select.Trigger>
      <Select.Popover
        className="min-w-[240px] border border-[#dedee0] bg-white p-1 shadow-lg outline-none"
        style={{ borderRadius: 16 }}
      >
        <ListBox selectionMode="multiple" className="outline-none">
          {options.map((option) => (
            <ListBox.Item
              key={option}
              id={option}
              textValue={option}
              className="cursor-pointer px-3 py-2 text-sm text-[#18181b] outline-none data-[focused]:bg-[#f5f5f5] data-[selected]:bg-[#0485f7]/[0.08]"
              style={{ borderRadius: 8 }}
            >
              {option}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  )
}

function FilterTimeField({
  value,
  onChange,
  'aria-label': ariaLabel,
}: {
  value: Time | null
  onChange: (next: Time | null) => void
  'aria-label': string
}) {
  return (
    <TimeField
      aria-label={ariaLabel}
      hourCycle={24}
      value={value}
      onChange={onChange}
      className="min-w-0 flex-1"
    >
      <TimeField.Group
        className="flex h-9 w-full items-center border border-[#dedee0] bg-white shadow-none"
        style={{ borderRadius: 8, paddingLeft: 12, paddingRight: 12 }}
      >
        <TimeField.Input className="min-w-0 flex-1 text-sm leading-5 text-[#18181b]">
          {(segment) => <TimeField.Segment segment={segment} />}
        </TimeField.Input>
        <TimeField.Suffix className="ms-2">
          <RiTimeLine size={16} className="text-[#71717a]" />
        </TimeField.Suffix>
      </TimeField.Group>
    </TimeField>
  )
}

type TicketsFiltersPopoverProps = {
  value: TicketsFiltersState
  onChange: (next: TicketsFiltersState) => void
}

export function TicketsFiltersPopover({
  value,
  onChange,
}: TicketsFiltersPopoverProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<TicketsFiltersState>(value)

  useEffect(() => {
    if (open) setDraft(value)
  }, [open, value])

  return (
    <Popover isOpen={open} onOpenChange={setOpen}>
      <Popover.Trigger
        className={cn(
          'inline-flex h-9 shrink-0 cursor-pointer items-center gap-2 border border-[#dedee0] text-sm font-medium leading-5 text-[#18181b] transition-colors outline-none',
          open ? 'bg-[#ebebec]' : 'bg-white hover:bg-[#f5f5f5]',
        )}
        style={{ borderRadius: 8, padding: '8px 16px' }}
      >
        <RiEqualizer2Line size={16} className="shrink-0 text-[#18181b]" />
        Фильтры
      </Popover.Trigger>

      <Popover.Content
        placement="bottom end"
        offset={8}
        className="w-[369px] border-0 bg-white p-0 text-[#18181b] outline-none"
        style={{
          borderRadius: 16,
          boxShadow:
            '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
        }}
      >
        <Popover.Dialog className="p-0 outline-none" style={{ borderRadius: 16 }}>
          <div
            className="flex flex-col"
            style={{ padding: '12px 20px 20px' }}
          >
            <Popover.Heading className="text-base font-semibold leading-6 text-[#18181b]">
              Фильтрация
            </Popover.Heading>

            <p
              className="text-sm leading-6 text-[#71717a]"
              style={{ marginTop: 4 }}
            >
              Найдите нераспределенные заявки
            </p>

            <div className="flex flex-col" style={{ marginTop: 16, gap: 16 }}>
              <MultiFilterSelect
                label="Вид работы"
                placeholder="Выберите вид работы"
                options={WORK_TYPE_OPTIONS}
                value={draft.workTypes}
                onChange={(workTypes) =>
                  setDraft((prev) => ({ ...prev, workTypes }))
                }
              />

              <MultiFilterSelect
                label="Причина неназначения"
                placeholder="Выберите причину"
                options={REASON_OPTIONS}
                value={draft.reasons}
                onChange={(reasons) =>
                  setDraft((prev) => ({ ...prev, reasons }))
                }
              />

              <div className="flex flex-col" style={{ gap: 4 }}>
                <span className="text-sm font-medium leading-6 text-[#18181b]">
                  Рабочий день
                </span>
                <div className="flex items-center" style={{ gap: 0 }}>
                  <FilterTimeField
                    aria-label="Начало окна"
                    value={parseTime(draft.timeFrom)}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        timeFrom: formatTime(next),
                      }))
                    }
                  />
                  <span
                    className="shrink-0 text-sm leading-5 text-[#71717a]"
                    style={{ width: 12, textAlign: 'center' }}
                  >
                    -
                  </span>
                  <FilterTimeField
                    aria-label="Конец окна"
                    value={parseTime(draft.timeTo)}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        timeTo: formatTime(next),
                      }))
                    }
                  />
                </div>
              </div>
            </div>

            <div className="flex" style={{ marginTop: 16, gap: 12 }}>
              <button
                type="button"
                className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-[#dedee0] bg-white text-sm font-medium leading-5 text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
                style={{ borderRadius: 8, padding: '8px 16px' }}
                onClick={() => setDraft(EMPTY_TICKETS_FILTERS)}
              >
                Сбросить
              </button>
              <button
                type="button"
                className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center bg-[#0485f7] text-sm font-medium leading-5 text-[#fcfcfc] transition-colors hover:bg-[#0374d9]"
                style={{ borderRadius: 8, padding: '8px 16px' }}
                onClick={() => {
                  onChange(draft)
                  setOpen(false)
                }}
              >
                Применить
              </button>
            </div>
          </div>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  )
}
