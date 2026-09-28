import { useState } from 'react'
import { Dropdown, Tooltip } from '@heroui/react'
import { Time } from '@internationalized/date'
import {
  RiArrowDownSLine,
  RiDeleteBinLine,
  RiDownload2Line,
  RiFileTextLine,
  RiInformationLine,
  RiLoopRightLine,
  RiUploadCloud2Line,
} from '@remixicon/react'
import { DropZone, FileTrigger, Button as AriaButton, isFileDropItem } from 'react-aria-components'

import { useGetRegionsQuery } from '@/features/catalogs'
import {
  AddressPointField,
  EMPTY_ADDRESS_POINT,
  type AddressPoint,
} from '@/features/personnel/ui/AddressPointField'
import { cn } from '@/shared/lib/cn'
import {
  AppModal,
  AppTooltipContent,
  FieldLabel,
  RebuildLevelField,
  WorkTimeField,
  buttonClass,
  type RebuildLevel,
} from '@/shared/ui'

import type { UploadTicketsResult } from '../api'
import { TICKETS_FILE_TYPES, downloadTicketsTemplate, formatFileSize, isTicketsFile } from '../lib/template'
import { useTicketCreate, useTicketsUpload } from '../lib/useTicketsUpload'
import { WORK_TYPE_OPTIONS } from './TicketsFiltersPopover'

type TicketsUploadDialogProps = {
  isOpen: boolean
  onClose: () => void
  /** Регион из шапки — выбран сразу. */
  defaultRegionId?: number | null
  /** Выбранный день, YYYY-MM-DD: на него вешаются строки без даты и новая заявка. */
  date: string
  onUploaded?: (result: UploadTicketsResult) => void
}

function InfoHint({ children }: { children: string }) {
  return (
    <Tooltip delay={200}>
      <Tooltip.Trigger className="inline-flex cursor-help text-muted outline-none">
        <RiInformationLine size={12} />
      </Tooltip.Trigger>
      <AppTooltipContent>{children}</AppTooltipContent>
    </Tooltip>
  )
}

/** Выпадающий список на ширину окна — регион и тип работ. */
function OptionsDropdown<K extends string | number>({
  label,
  placeholder,
  options,
  value,
  onChange,
}: {
  label: string
  placeholder: string
  options: { id: K; label: string }[]
  value: K | null
  onChange: (next: K) => void
}) {
  const selected = options.find((item) => item.id === value) ?? null
  return (
    <Dropdown>
      <Dropdown.Trigger
        aria-label={label}
        className="flex h-9 w-full cursor-pointer items-center justify-between rounded-[8px] border border-border bg-surface pr-3 pl-3 text-sm leading-5 outline-none transition-colors hover:bg-surface-hover focus-visible:border-focus"
      >
        <span className={cn('truncate', selected ? 'text-foreground' : 'text-muted')}>
          {selected?.label ?? placeholder}
        </span>
        <RiArrowDownSLine size={16} className="shrink-0 text-foreground" />
      </Dropdown.Trigger>
      <Dropdown.Popover
        placement="bottom start"
        offset={4}
        className="w-[402px] max-w-[calc(100vw-80px)] border-0 bg-surface p-1 outline-none"
        style={{ borderRadius: 12, boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)' }}
      >
        <Dropdown.Menu
          aria-label={label}
          selectionMode="single"
          selectedKeys={value != null ? new Set([String(value)]) : new Set()}
          onAction={(key) => {
            const next = options.find((item) => String(item.id) === String(key))
            if (next) onChange(next.id)
          }}
          className="flex flex-col outline-none"
        >
          {options.map((item) => (
            <Dropdown.Item
              key={item.id}
              id={String(item.id)}
              textValue={item.label}
              className="flex h-9 cursor-pointer items-center rounded-[8px] px-3 text-sm leading-5 font-medium text-foreground outline-none data-[focused]:bg-surface-hover data-[selected]:bg-surface-hover"
            >
              {item.label}
            </Dropdown.Item>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  )
}

const WORK_TYPES = WORK_TYPE_OPTIONS.map((item) => ({ id: item, label: item }))

/** Авария вытесняет работы и сдвигает маршруты — по умолчанию план пересобирается целиком. */
const EMERGENCY_WORK_TYPE = 'Аварийные работы'

const clock = (time: Time) => `${String(time.hour).padStart(2, '0')}:${String(time.minute).padStart(2, '0')}`

/**
 * Modal «Загрузить заявки»: регион, файл выгрузки, уровень перестроения плана, шаблон.
 * Ссылка «Нажмите здесь» переключает его на «Добавить заявку» — одну заявку вручную.
 */
export function TicketsUploadDialog({ isOpen, onClose, defaultRegionId = null, date, onUploaded }: TicketsUploadDialogProps) {
  const { data: regions = [] } = useGetRegionsQuery()
  const [mode, setMode] = useState<'file' | 'single'>('file')
  const [regionId, setRegionId] = useState<number | null>(defaultRegionId)
  const [file, setFile] = useState<File | null>(null)
  const [level, setLevel] = useState<RebuildLevel>('fix')
  const [address, setAddress] = useState<AddressPoint>(EMPTY_ADDRESS_POINT)
  const [timeFrom, setTimeFrom] = useState<Time | null>(new Time(9, 0))
  const [timeTo, setTimeTo] = useState<Time | null>(new Time(18, 0))
  const [workType, setWorkType] = useState<string | null>(null)
  const { upload, isUploading } = useTicketsUpload(onUploaded)
  const { create, isCreating } = useTicketCreate(onUploaded)
  const [prevOpen, setPrevOpen] = useState(isOpen)

  // Каждое открытие — с чистого листа и регионом из шапки.
  if (prevOpen !== isOpen) {
    setPrevOpen(isOpen)
    if (isOpen) {
      setMode('file')
      setRegionId(defaultRegionId)
      setFile(null)
      setLevel('fix')
      setAddress(EMPTY_ADDRESS_POINT)
      setTimeFrom(new Time(9, 0))
      setTimeTo(new Time(18, 0))
      setWorkType(null)
    }
  }

  const region = regions.find((item) => item.id === regionId) ?? null
  const canUpload = region != null && file != null && !isUploading
  const badWindow = timeFrom != null && timeTo != null && timeTo.compare(timeFrom) <= 0
  const canCreate =
    region != null &&
    address.confirmed &&
    address.point != null &&
    timeFrom != null && timeTo != null && !badWindow && workType != null && !isCreating

  const pick = (files: File[]) => {
    const next = files.find(isTicketsFile)
    if (next) setFile(next)
  }

  const submitFile = async () => {
    if (!region || !file) return
    onClose()
    await upload({ file, regionId: region.id, date, remakeLevel: level })
  }

  const submitSingle = async () => {
    if (!region || !timeFrom || !timeTo || !workType || !address.point) return
    const done = await create({
      region_id: region.id,
      date,
      address: address.address.trim(),
      lon: address.point[0],
      lat: address.point[1],
      start: clock(timeFrom),
      end: clock(timeTo),
      work_type: workType,
      remake_level: level,
    })
    if (done) onClose()
  }

  if (mode === 'single') {
    return (
      <AppModal
        isOpen={isOpen}
        onClose={onClose}
        title="Добавить заявку"
        description="Новая заявка будет распределена в текущем плане"
        footer={
          <>
            <button type="button" onClick={onClose} className={buttonClass.outline}>
              Отмена
            </button>
            <button type="button" disabled={!canCreate} onClick={() => void submitSingle()} className={buttonClass.primary}>
              {isCreating ? 'Добавляем…' : 'Добавить'}
            </button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <FieldLabel required>Адрес заявки</FieldLabel>
            <AddressPointField
              value={address}
              onChange={setAddress}
              label="Адрес заявки"
              pointName="заявку"
              doneHint="Сюда приедет инженер"
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel required>Время заявки</FieldLabel>
            <div className="flex items-center gap-1">
              <WorkTimeField aria-label="Начало окна заявки" value={timeFrom} onChange={setTimeFrom} />
              <span className="text-sm leading-5 text-muted">-</span>
              <WorkTimeField aria-label="Окончание окна заявки" value={timeTo} onChange={setTimeTo} />
            </div>
            {badWindow ? <p className="text-xs leading-5 text-danger">Окончание должно быть позже начала</p> : null}
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel required hint={<InfoHint>От типа работ зависит нужный навык инженера</InfoHint>}>
              Тип работ
            </FieldLabel>
            <OptionsDropdown
              label="Тип работ"
              placeholder="Выберите тип работ"
              options={WORK_TYPES}
              value={workType}
              onChange={(next) => {
                setWorkType(next)
                setLevel(next === EMERGENCY_WORK_TYPE ? 'free' : 'fix')
              }}
            />
          </div>
          <RebuildLevelField value={level} onChange={setLevel} />
        </div>
      </AppModal>
    )
  }

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title="Загрузить заявки"
      description={
        <>
          Новые заявки будут добавлены, существующие из того же источника - обновлены.
          <span className="mt-2 block">
            Чтобы добавить одну заявку{' '}
            <button
              type="button"
              onClick={() => setMode('single')}
              className="cursor-pointer text-link outline-none hover:underline focus-visible:underline"
            >
              Нажмите здесь
            </button>
          </span>
        </>
      }
      footer={
        <>
          <button
            type="button"
            onClick={downloadTicketsTemplate}
            className="mr-auto flex h-9 cursor-pointer items-center gap-2 text-sm leading-5 font-medium text-foreground transition-colors hover:text-link"
          >
            <RiDownload2Line size={16} />
            Скачать шаблон
          </button>
          <button type="button" onClick={onClose} className={buttonClass.outline}>
            Отмена
          </button>
          <button type="button" disabled={!canUpload} onClick={() => void submitFile()} className={buttonClass.primary}>
            Загрузить
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <FieldLabel required hint={<InfoHint>Все заявки должны относиться к выбранному региону</InfoHint>}>
            Регион
          </FieldLabel>
          <OptionsDropdown
            label="Регион"
            placeholder="Выберите регион"
            options={regions.map((item) => ({ id: item.id, label: item.name }))}
            value={regionId}
            onChange={setRegionId}
          />
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel required>Выгрузка</FieldLabel>
          {file ? (
            <div className="flex items-center gap-3 rounded-[8px] border border-border bg-surface p-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-surface-tertiary text-foreground">
                <RiFileTextLine size={16} />
              </span>
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-xs leading-5 font-medium text-foreground">{file.name}</span>
                <span className="text-xs leading-4 text-muted">{formatFileSize(file.size)}</span>
              </div>
              <FileTrigger acceptedFileTypes={TICKETS_FILE_TYPES} onSelect={(list) => list && pick(Array.from(list))}>
                <AriaButton
                  aria-label="Заменить файл"
                  className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[8px] bg-surface-tertiary text-foreground outline-none transition-colors hover:bg-default-hover"
                >
                  <RiLoopRightLine size={16} />
                </AriaButton>
              </FileTrigger>
              <button
                type="button"
                aria-label="Убрать файл"
                onClick={() => setFile(null)}
                className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[8px] bg-danger-soft text-danger transition-colors hover:bg-danger-soft-hover"
              >
                <RiDeleteBinLine size={16} />
              </button>
            </div>
          ) : (
            <DropZone
              aria-label="Выгрузка заявок"
              getDropOperation={() => 'copy'}
              onDrop={async (event) => {
                const files: File[] = []
                for (const item of event.items) {
                  if (isFileDropItem(item)) files.push(await item.getFile())
                }
                pick(files)
              }}
              className="flex h-[148px] flex-col items-center justify-center rounded-[8px] border border-dashed border-border bg-surface-hover outline-none transition-colors data-[drop-target]:border-focus data-[drop-target]:bg-accent/[0.06]"
            >
              <FileTrigger acceptedFileTypes={TICKETS_FILE_TYPES} onSelect={(list) => list && pick(Array.from(list))}>
                <AriaButton className="flex size-full cursor-pointer flex-col items-center justify-center gap-2 outline-none">
                  <RiUploadCloud2Line size={24} className="text-muted" />
                  <span className="flex flex-col items-center">
                    <span className="text-base leading-7 font-medium text-foreground">Загрузите заявки</span>
                    <span className="text-xs leading-5 text-muted">
                      Нажмите на это поле или перетащите
                      <br />в него csv или json файл
                    </span>
                  </span>
                </AriaButton>
              </FileTrigger>
            </DropZone>
          )}
        </div>

        <RebuildLevelField value={level} onChange={setLevel} />
      </div>
    </AppModal>
  )
}
