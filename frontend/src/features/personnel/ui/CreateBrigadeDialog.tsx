import { useEffect, useState } from 'react'
import { ListBox, Select, toast } from '@heroui/react'
import { Time } from '@internationalized/date'
import { RiArrowDownSLine } from '@remixicon/react'

import { useGetRegionsQuery } from '@/features/catalogs'
import { useCreateBrigadeMutation } from '@/features/personnel/api'
import type { PersonnelBrigade } from '@/features/personnel/types'
import { cn } from '@/shared/lib/cn'
import { AppModal, buttonClass } from '@/shared/ui'

import { errorReason } from '../lib/errors'
import { formatTime } from '../lib/time'
import { WEEKDAYS } from '../lib/weekdays'
import {
  AddressPointField,
  EMPTY_ADDRESS_POINT,
  type AddressPoint,
} from './AddressPointField'
import { FieldLabel, Hint, TextInput, ToggleChip, WorkTimeField } from './formParts'

type CreateBrigadeDialogProps = {
  isOpen: boolean
  onClose: () => void
  /** Регион, в котором уже есть выбранная бригада — подставляется в форме. */
  defaultRegionId?: number | null
  onCreated: (brigade: PersonnelBrigade) => void
}

function RegionSelect({
  value,
  onChange,
  options,
}: {
  value: number | null
  onChange: (next: number) => void
  options: { id: number; label: string }[]
}) {
  return (
    <Select
      aria-label="Регион"
      className="w-full"
      placeholder="Выберите регион"
      value={value}
      onChange={(key) => {
        if (key != null) onChange(key as number)
      }}
    >
      <Select.Trigger
        className={cn(
          'flex h-9 w-full items-center justify-between gap-2 border border-border bg-surface text-left shadow-none outline-none',
          'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-focus',
        )}
        style={{ borderRadius: 8, padding: '8px 12px' }}
      >
        <Select.Value className="min-w-0 flex-1 truncate text-sm leading-5 text-foreground data-[placeholder]:text-muted" />
        <Select.Indicator className="shrink-0 text-foreground">
          <RiArrowDownSLine size={16} />
        </Select.Indicator>
      </Select.Trigger>
      <Select.Popover
        className="min-w-[240px] border border-border bg-surface p-1 shadow-lg outline-none"
        style={{ borderRadius: 16 }}
      >
        <ListBox className="outline-none">
          {options.map((option) => (
            <ListBox.Item
              key={option.id}
              id={option.id}
              textValue={option.label}
              className="cursor-pointer px-3 py-2 text-sm text-foreground outline-none data-[focused]:bg-surface-hover data-[selected]:bg-surface-hover"
              style={{ borderRadius: 8 }}
            >
              {option.label}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  )
}

/** Окно «Добавить бригаду»: регион, название, офис, смена и рабочие дни. */
export function CreateBrigadeDialog({
  isOpen,
  onClose,
  defaultRegionId = null,
  onCreated,
}: CreateBrigadeDialogProps) {
  const { data: regions = [] } = useGetRegionsQuery()
  const [createBrigade, { isLoading }] = useCreateBrigadeMutation()
  const [regionId, setRegionId] = useState<number | null>(defaultRegionId)
  const [name, setName] = useState('')
  const [office, setOffice] = useState<AddressPoint>(EMPTY_ADDRESS_POINT)
  const [workDays, setWorkDays] = useState([1, 2, 3, 4, 5, 6, 7])
  const [timeFrom, setTimeFrom] = useState<Time | null>(new Time(9, 0))
  const [timeTo, setTimeTo] = useState<Time | null>(new Time(22, 0))
  const [prevOpen, setPrevOpen] = useState(isOpen)

  if (prevOpen !== isOpen) {
    setPrevOpen(isOpen)
    if (isOpen) {
      setRegionId(defaultRegionId)
      setName('')
      setOffice(EMPTY_ADDRESS_POINT)
      setWorkDays([1, 2, 3, 4, 5, 6, 7])
      setTimeFrom(new Time(9, 0))
      setTimeTo(new Time(22, 0))
    }
  }

  useEffect(() => {
    if (!isOpen || regionId != null || regions.length === 0) return
    const preferred =
      defaultRegionId != null && regions.some((item) => item.id === defaultRegionId)
        ? defaultRegionId
        : (regions[0]?.id ?? null)
    if (preferred != null) setRegionId(preferred)
  }, [isOpen, regionId, regions, defaultRegionId])

  useEffect(() => {
    if (!isOpen || regionId == null || name.trim()) return
    const region = regions.find((item) => item.id === regionId)
    if (region) setName(`Бригада ${region.name}`)
  }, [isOpen, regionId, regions, name])

  const hoursValid =
    timeFrom != null && timeTo != null && timeTo.compare(timeFrom) > 0
  const canSubmit =
    regionId != null &&
    name.trim() !== '' &&
    office.confirmed &&
    office.point != null &&
    workDays.length > 0 &&
    hoursValid &&
    !isLoading

  const submit = async () => {
    if (!canSubmit || regionId == null || office.point == null || timeFrom == null || timeTo == null) {
      return
    }
    try {
      const created = await createBrigade({
        region_id: regionId,
        name: name.trim(),
        office_address: office.address.trim(),
        office_lat: office.point[1],
        office_lon: office.point[0],
        work_days: [...workDays].sort(),
        start_work: formatTime(timeFrom),
        end_work: formatTime(timeTo),
      }).unwrap()
      toast.success('Бригада добавлена')
      onCreated(created)
      onClose()
    } catch (error) {
      toast.danger('Бригада не добавлена', { description: errorReason(error) })
    }
  }

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title="Добавить бригаду"
      description="Бригада привязывается к региону: в него же потом грузятся заявки и инженеры"
      className="w-[480px]"
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass.outline}>
            Отмена
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => void submit()}
            className={buttonClass.primary}
          >
            {isLoading ? 'Создаём…' : 'Добавить'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <FieldLabel required>Регион</FieldLabel>
          <RegionSelect
            value={regionId}
            onChange={(next) => {
              setRegionId(next)
              const region = regions.find((item) => item.id === next)
              if (region) setName(`Бригада ${region.name}`)
            }}
            options={regions.map((item) => ({ id: item.id, label: item.name }))}
          />
        </div>

        <label className="flex flex-col gap-1">
          <FieldLabel required>Название</FieldLabel>
          <TextInput
            aria-label="Название бригады"
            value={name}
            onChange={setName}
            placeholder="Бригада Юго-восток"
            maxLength={200}
          />
        </label>

        <div className="flex flex-col gap-1">
          <FieldLabel required>Адрес офиса</FieldLabel>
          <AddressPointField
            value={office}
            onChange={setOffice}
            label="Адрес офиса"
            pointName="офис"
            doneHint="Отсюда инженеры начинают день"
          />
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel required>Рабочий график</FieldLabel>
          <div className="flex gap-1 pt-1">
            {WEEKDAYS.map(({ day, label }) => (
              <ToggleChip
                key={day}
                active={workDays.includes(day)}
                onToggle={() =>
                  setWorkDays((prev) =>
                    prev.includes(day) ? prev.filter((item) => item !== day) : [...prev, day].sort(),
                  )
                }
                className="!h-8 min-w-0 flex-1 justify-center !px-0"
              >
                {label}
              </ToggleChip>
            ))}
          </div>
          {workDays.length === 0 ? (
            <p className="text-xs leading-5 text-danger">Выберите хотя бы один день</p>
          ) : (
            <Hint>Инженеры без своего графика работают в эти дни</Hint>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel required>Рабочий день</FieldLabel>
          <div className="flex items-center">
            <WorkTimeField
              aria-label="Начало рабочего дня"
              value={timeFrom}
              onChange={setTimeFrom}
            />
            <span className="shrink-0 px-1 text-sm leading-5 text-muted">-</span>
            <WorkTimeField aria-label="Конец рабочего дня" value={timeTo} onChange={setTimeTo} />
          </div>
          {!hoursValid ? (
            <p className="text-xs leading-5 text-danger">Конец дня должен быть позже начала</p>
          ) : (
            <Hint>Обед 13:00–14:00 настраивается потом в карточке бригады</Hint>
          )}
        </div>
      </div>
    </AppModal>
  )
}
