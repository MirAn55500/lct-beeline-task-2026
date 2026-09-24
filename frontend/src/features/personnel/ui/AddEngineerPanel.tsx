import { useEffect, useState, type ReactNode } from 'react'
import {
  ListBox,
  ProgressCircle,
  ScrollShadow,
  Select,
  TimeField,
  toast,
} from '@heroui/react'
import { Time } from '@internationalized/date'
import {
  RiArrowDownSLine,
  RiDeleteBinLine,
  RiRefreshLine,
  RiTimeLine,
  RiUploadCloud2Line,
} from '@remixicon/react'
import {
  Button,
  DropZone,
  FileTrigger,
  Text,
  isFileDropItem,
} from 'react-aria-components'

import { useCreateEngineerMutation } from '@/features/personnel/api'
import {
  TRANSPORT_LABEL,
  createUploadBatch,
  type SkillCode,
  type TransportCode,
} from '@/features/personnel/mocks'
import type { PersonnelBrigade, PersonnelEngineer } from '@/features/personnel/types'
import { WORK_TYPE_OPTIONS } from '@/features/tickets'
import { cn } from '@/shared/lib/cn'
import { pluralRu } from '@/shared/lib/text'
import { AppPanel } from '@/shared/ui'

import { TRANSPORT_ICON } from './transportIcons'

type AddMode = 'manual' | 'file'

const MODES: { id: AddMode; label: string }[] = [
  { id: 'manual', label: 'Вручную' },
  { id: 'file', label: 'Файлом' },
]

const TRANSPORT_ORDER: TransportCode[] = ['car', 'public', 'bike', 'walking']

// Навыки в форме — виды работ из заявок; в таблице они сведены в три группы.
const WORK_TYPE_TO_SKILL: Record<string, SkillCode> = {
  'Аварийные работы': 'emergency',
  Подключение: 'connection',
  Дозаказ: 'connection',
  Ремонт: 'local',
}

// Порядок дней как в макете.
const WEEK_DAYS = ['Сб', 'Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт'] as const
type WeekDay = (typeof WEEK_DAYS)[number]

const AVATAR_MAX_BYTES = 5 * 1024 * 1024

function formatTime(value: Time): string {
  return `${String(value.hour).padStart(2, '0')}:${String(value.minute).padStart(2, '0')}:00`
}

function FieldLabel({ children, required }: { children: ReactNode; required?: boolean }) {
  return (
    <span className="text-sm font-medium leading-6 text-[#18181b]">
      {children}
      {required ? <span className="ms-1 text-[#ef2c56]">*</span> : null}
    </span>
  )
}

function Hint({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-5 text-[#71717a]">{children}</p>
}

function ToggleChip({
  active,
  onToggle,
  className,
  children,
}: {
  active: boolean
  onToggle: () => void
  className?: string
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      className={cn(
        'inline-flex h-7 cursor-pointer items-center gap-1 px-3 text-sm font-medium leading-5 transition-colors',
        active
          ? 'bg-[#0485f7] text-[#fcfcfc] hover:bg-[#0374d9]'
          : 'bg-[#ebebec] text-[#18181b] hover:bg-[#e0e0e2]',
        className,
      )}
      style={{ borderRadius: 8 }}
    >
      {children}
    </button>
  )
}

function TextInput({
  value,
  onChange,
  placeholder,
  'aria-label': ariaLabel,
}: {
  value: string
  onChange: (next: string) => void
  placeholder: string
  'aria-label': string
}) {
  return (
    <input
      type="text"
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="h-9 w-full border border-[#dedee0] bg-white px-3 text-sm leading-5 text-[#18181b] outline-none placeholder:text-[#71717a] focus-visible:border-[#0485f7]"
      style={{ borderRadius: 8 }}
    />
  )
}

function SingleSelect<K extends string | number>({
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
  return (
    <Select
      aria-label={label}
      className="w-full"
      placeholder={placeholder}
      value={value}
      onChange={(key) => {
        if (key != null) onChange(key as K)
      }}
    >
      <Select.Trigger
        className={cn(
          'flex h-9 w-full items-center justify-between gap-2 border border-[#dedee0] bg-white text-left shadow-none outline-none',
          'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-[#0485f7]',
        )}
        style={{ borderRadius: 8, padding: '8px 12px' }}
      >
        <Select.Value className="min-w-0 flex-1 truncate text-sm leading-5 text-[#18181b] data-[placeholder]:text-[#71717a]" />
        <Select.Indicator className="shrink-0 text-[#18181b]">
          <RiArrowDownSLine size={16} />
        </Select.Indicator>
      </Select.Trigger>
      <Select.Popover
        className="min-w-[240px] border border-[#dedee0] bg-white p-1 shadow-lg outline-none"
        style={{ borderRadius: 16 }}
      >
        <ListBox className="outline-none">
          {options.map((option) => (
            <ListBox.Item
              key={option.id}
              id={option.id}
              textValue={option.label}
              className="cursor-pointer px-3 py-2 text-sm text-[#18181b] outline-none data-[focused]:bg-[#f5f5f5] data-[selected]:bg-[#0485f7]/[0.08]"
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

function WorkTimeField({
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

function formatMegabytes(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
}

function AvatarField({
  file,
  onChange,
}: {
  file: File | null
  onChange: (next: File | null) => void
}) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  const accept = (files: File[]) => {
    const image = files.find((item) => /\.(jpe?g|png)$/i.test(item.name))
    if (!image) {
      toast.danger('Нужен jpeg или png файл')
      return
    }
    if (image.size > AVATAR_MAX_BYTES) {
      toast.danger('Фото весит больше 5 МБ')
      return
    }
    onChange(image)
  }

  if (file) {
    return (
      <div
        className="flex items-center gap-3 border border-[#dedee0] bg-white p-3"
        style={{ borderRadius: 8 }}
      >
        {previewUrl ? (
          <img
            src={previewUrl}
            alt=""
            className="size-8 shrink-0 object-cover"
            style={{ borderRadius: 8 }}
          />
        ) : null}
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-xs font-medium leading-5 text-[#18181b]">
            {file.name.replace(/\.[^.]+$/, '')}
          </span>
          <span className="text-xs leading-4 text-[#71717a]">{formatMegabytes(file.size)}</span>
        </span>
        <FileTrigger
          acceptedFileTypes={['image/jpeg', 'image/png']}
          onSelect={(list) => list && accept(Array.from(list))}
        >
          <Button
            aria-label="Заменить фото"
            className="flex size-8 shrink-0 cursor-pointer items-center justify-center border border-[#dedee0] bg-white text-[#18181b] outline-none transition-colors hover:bg-[#f5f5f5]"
            style={{ borderRadius: 8 }}
          >
            <RiRefreshLine size={16} />
          </Button>
        </FileTrigger>
        <button
          type="button"
          aria-label="Удалить фото"
          onClick={() => onChange(null)}
          className="flex size-8 shrink-0 cursor-pointer items-center justify-center bg-[#ff383c]/15 text-[#ff383c] transition-colors hover:bg-[#ff383c]/25"
          style={{ borderRadius: 8 }}
        >
          <RiDeleteBinLine size={16} />
        </button>
      </div>
    )
  }

  return (
    <DropZone
      aria-label="Загрузка фото сотрудника"
      getDropOperation={() => 'copy'}
      onDrop={async (event) => {
        const files: File[] = []
        for (const item of event.items) {
          if (isFileDropItem(item)) files.push(await item.getFile())
        }
        accept(files)
      }}
      className={cn(
        'flex w-full flex-col items-center justify-center border border-dashed border-[#dedee0] bg-[#f5f5f5] px-4 py-3 text-center outline-none transition-colors',
        'data-[drop-target]:border-[#0485f7] data-[drop-target]:bg-[#0485f7]/[0.06]',
      )}
      style={{ borderRadius: 8 }}
    >
      <FileTrigger
        acceptedFileTypes={['image/jpeg', 'image/png']}
        onSelect={(list) => list && accept(Array.from(list))}
      >
        <Button className="flex cursor-pointer flex-col items-center gap-1 bg-transparent outline-none">
          <span className="flex items-center gap-1 text-xs font-medium leading-5 text-[#18181b]">
            <RiUploadCloud2Line size={16} className="shrink-0" />
            <Text slot="label">Загрузите фото сотрудника</Text>
          </span>
          <span className="text-xs leading-5 text-[#71717a]">
            Нажмите на это поле или перетащите в него jpeg или png файл весом не
            более 5 мб
          </span>
        </Button>
      </FileTrigger>
    </DropZone>
  )
}

type ManualDraft = {
  name: string
  address: string
  avatar: File | null
  transports: TransportCode[]
  workTypes: string[]
  brigadeId: number | null
  days: WeekDay[]
  timeFrom: Time | null
  timeTo: Time | null
}

function toggleIn<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((entry) => entry !== item) : [...list, item]
}

type AddEngineerPanelProps = {
  brigades: PersonnelBrigade[]
  defaultBrigadeId: number | null
  engineers: PersonnelEngineer[]
  onAdd: (added: PersonnelEngineer[]) => void
  onClose: () => void
}

export function AddEngineerPanel({
  brigades,
  defaultBrigadeId,
  engineers,
  onAdd,
  onClose,
}: AddEngineerPanelProps) {
  const [mode, setMode] = useState<AddMode>('manual')
  const [submitting, setSubmitting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [createEngineer] = useCreateEngineerMutation()
  const [draft, setDraft] = useState<ManualDraft>(() => ({
    name: '',
    address: '',
    avatar: null,
    transports: [],
    workTypes: [],
    brigadeId: defaultBrigadeId,
    days: ['Пн', 'Вт', 'Ср', 'Чт', 'Пт'],
    timeFrom: new Time(9, 0),
    timeTo: new Time(18, 0),
  }))

  const patch = (next: Partial<ManualDraft>) => setDraft((prev) => ({ ...prev, ...next }))

  const isValid =
    draft.name.trim() !== '' &&
    draft.transports.length > 0 &&
    draft.workTypes.length > 0 &&
    draft.brigadeId != null &&
    draft.timeFrom != null &&
    draft.timeTo != null

  const submitManual = async (snapshot: ManualDraft) => {
    if (
      snapshot.brigadeId == null ||
      snapshot.timeFrom == null ||
      snapshot.timeTo == null
    ) {
      return
    }
    setSubmitting(true)
    const skills = [...new Set(snapshot.workTypes.map((type) => WORK_TYPE_TO_SKILL[type]!))]
    const transport = TRANSPORT_ORDER.find((code) => snapshot.transports.includes(code))!
    try {
      const created = await createEngineer({
        name: snapshot.name.trim(),
        brigade_id: snapshot.brigadeId,
        transport,
        skills,
        start_work: formatTime(snapshot.timeFrom),
        end_work: formatTime(snapshot.timeTo),
      }).unwrap()
      onAdd([created])
      toast.success('Инженер добавлен')
      onClose()
    } catch {
      toast.danger('Инженер не добавлен', {
        description: 'Что-то пошло не так',
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => void submitManual(snapshot),
        },
      })
    } finally {
      setSubmitting(false)
    }
  }

  const uploadFile = async (file: File) => {
    const brigadeId = draft.brigadeId ?? defaultBrigadeId
    if (brigadeId == null) return
    setUploading(true)
    // Пока нет отдельной ручки загрузки файла — создаём пачку через POST /engineers.
    const batch = createUploadBatch(brigadeId, engineers)
    try {
      const created: PersonnelEngineer[] = []
      for (const item of batch) {
        const row = await createEngineer({
          name: item.name,
          brigade_id: brigadeId,
          transport: item.transport,
          skills: item.skills,
          start_work: '09:00:00',
          end_work: '18:00:00',
        }).unwrap()
        created.push(row)
      }
      onAdd(created)
      toast.success('Загрузка завершена', {
        description: `Добавлено ${created.length} ${pluralRu(created.length, ['инженер', 'инженера', 'инженеров'])}`,
      })
      onClose()
    } catch {
      toast.danger('Не удалось завершить загрузку', {
        description: `Файл «${file.name}» не принят. Проверьте формат и попробуйте снова`,
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => void uploadFile(file),
        },
      })
    } finally {
      setUploading(false)
    }
  }

  const acceptSheets = (files: File[]) => {
    const file = files.find((item) => /\.(csv|xlsx?)$/i.test(item.name))
    if (!file) {
      toast.danger('Нужен excel или csv файл')
      return
    }
    void uploadFile(file)
  }

  return (
    <AppPanel className="flex min-h-0 w-[346px] shrink-0 flex-col">
      <div className="flex shrink-0 flex-col gap-4 px-5 pt-5">
        <div className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold leading-7 text-[#18181b]">Добавить инженера</h2>
          <p className="text-sm leading-6 text-[#71717a]">Заполните информацию о сотруднике</p>
        </div>

        <div
          role="tablist"
          aria-label="Способ добавления"
          className="flex h-9 items-center bg-[#ebebec]"
          style={{ borderRadius: 8, padding: 2 }}
        >
          {MODES.map((item) => {
            const active = item.id === mode
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={active}
                disabled={uploading || submitting}
                onClick={() => setMode(item.id)}
                className={cn(
                  'h-8 flex-1 cursor-pointer text-sm font-medium leading-6 transition-colors disabled:cursor-not-allowed',
                  active
                    ? 'bg-white text-[#18181b] shadow-[0_1px_2px_rgb(0_0_0/0.06)]'
                    : 'text-[#71717a] hover:text-[#18181b]',
                )}
                style={{ borderRadius: 6 }}
              >
                {item.label}
              </button>
            )
          })}
        </div>
      </div>

      {mode === 'manual' ? (
        <>
          <ScrollShadow
            hideScrollBar
            size={40}
            className="min-h-0 flex-1"
            orientation="vertical"
          >
            <div className="flex flex-col gap-4 px-5 py-4">
              <label className="flex flex-col gap-1">
                <FieldLabel required>ФИО инженера</FieldLabel>
                <TextInput
                  aria-label="ФИО инженера"
                  value={draft.name}
                  onChange={(name) => patch({ name })}
                  placeholder="Введите ФИО"
                />
              </label>

              <label className="flex flex-col gap-1">
                <FieldLabel>Домашний адрес</FieldLabel>
                <TextInput
                  aria-label="Домашний адрес"
                  value={draft.address}
                  onChange={(address) => patch({ address })}
                  placeholder="Введите адрес"
                />
              </label>

              <div className="flex flex-col gap-1">
                <FieldLabel>Аватар</FieldLabel>
                <AvatarField file={draft.avatar} onChange={(avatar) => patch({ avatar })} />
              </div>

              <div className="flex flex-col gap-2">
                <FieldLabel required>Доступный транспорт</FieldLabel>
                <div className="flex flex-wrap gap-1.5">
                  {TRANSPORT_ORDER.map((code) => {
                    const Icon = TRANSPORT_ICON[code]
                    return (
                      <ToggleChip
                        key={code}
                        active={draft.transports.includes(code)}
                        onToggle={() => patch({ transports: toggleIn(draft.transports, code) })}
                      >
                        <Icon size={16} className="shrink-0" />
                        {TRANSPORT_LABEL[code]}
                      </ToggleChip>
                    )
                  })}
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <FieldLabel required>Навыки</FieldLabel>
                <div className="flex flex-wrap gap-1.5">
                  {WORK_TYPE_OPTIONS.map((type) => (
                    <ToggleChip
                      key={type}
                      active={draft.workTypes.includes(type)}
                      onToggle={() => patch({ workTypes: toggleIn(draft.workTypes, type) })}
                    >
                      {type}
                    </ToggleChip>
                  ))}
                </div>
              </div>

              <div className="h-px w-full bg-[#dedee0]" />

              <div className="flex flex-col gap-1">
                <FieldLabel required>Бригада</FieldLabel>
                <SingleSelect
                  label="Бригада"
                  placeholder="Выберите бригаду"
                  options={brigades.map((brigade) => ({ id: brigade.id, label: brigade.name }))}
                  value={draft.brigadeId}
                  onChange={(brigadeId) => patch({ brigadeId })}
                />
                <Hint>Бригада определяет офис и рабочее время</Hint>
              </div>

              <div className="flex flex-col gap-2">
                <FieldLabel>Рабочий график</FieldLabel>
                <div className="flex gap-1.5">
                  {WEEK_DAYS.map((day) => (
                    <ToggleChip
                      key={day}
                      className="min-w-0 flex-1 justify-center px-0"
                      active={draft.days.includes(day)}
                      onToggle={() => patch({ days: toggleIn(draft.days, day) })}
                    >
                      {day}
                    </ToggleChip>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <FieldLabel required>Рабочий день</FieldLabel>
                <div className="flex items-center">
                  <WorkTimeField
                    aria-label="Начало рабочего дня"
                    value={draft.timeFrom}
                    onChange={(timeFrom) => patch({ timeFrom })}
                  />
                  <span
                    className="shrink-0 text-sm leading-5 text-[#71717a]"
                    style={{ width: 12, textAlign: 'center' }}
                  >
                    -
                  </span>
                  <WorkTimeField
                    aria-label="Конец рабочего дня"
                    value={draft.timeTo}
                    onChange={(timeTo) => patch({ timeTo })}
                  />
                </div>
              </div>
            </div>
          </ScrollShadow>

          <div className="flex shrink-0 gap-2 px-5 pt-2 pb-5">
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-[#dedee0] bg-white text-sm font-medium leading-5 text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
              style={{ borderRadius: 8, padding: '8px 16px' }}
            >
              Отмена
            </button>
            <button
              type="button"
              disabled={!isValid || submitting}
              onClick={() => void submitManual(draft)}
              className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center bg-[#0485f7] text-sm font-medium leading-5 text-[#fcfcfc] transition-colors hover:bg-[#0374d9] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-[#0485f7]"
              style={{ borderRadius: 8, padding: '8px 16px' }}
            >
              {submitting ? 'Добавляем…' : 'Добавить'}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="flex min-h-0 flex-1 px-5 py-4">
            {uploading ? (
              <div
                className="flex w-full flex-1 flex-col items-center justify-center gap-3 border border-dashed border-[#dedee0] bg-[#f5f5f5] px-5 text-center"
                style={{ borderRadius: 8 }}
              >
                <ProgressCircle
                  isIndeterminate
                  aria-label="Загружаем инженеров"
                  size="md"
                  className="size-9"
                >
                  <ProgressCircle.Track>
                    <ProgressCircle.TrackCircle className="stroke-[#ebebec]" />
                    <ProgressCircle.FillCircle className="stroke-[#0485f7]" />
                  </ProgressCircle.Track>
                </ProgressCircle>
                <div className="flex flex-col items-center">
                  <p className="text-base font-medium leading-7 text-[#18181b]">
                    Загружаем инженеров
                  </p>
                  <p className="text-xs leading-5 text-[#71717a]">
                    Это не займет больше 5 секунд
                  </p>
                </div>
              </div>
            ) : (
              <DropZone
                aria-label="Загрузка инженеров"
                getDropOperation={() => 'copy'}
                onDrop={async (event) => {
                  const files: File[] = []
                  for (const item of event.items) {
                    if (isFileDropItem(item)) files.push(await item.getFile())
                  }
                  acceptSheets(files)
                }}
                className={cn(
                  'flex w-full flex-1 flex-col items-center justify-center border border-dashed border-[#dedee0] bg-[#f5f5f5] px-5 text-center outline-none transition-colors',
                  'data-[drop-target]:border-[#0485f7] data-[drop-target]:bg-[#0485f7]/[0.06]',
                  'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:-outline-offset-1 data-[focus-visible]:outline-[#0485f7]',
                )}
                style={{ borderRadius: 8 }}
              >
                <FileTrigger
                  acceptedFileTypes={[
                    '.csv',
                    'text/csv',
                    '.xlsx',
                    '.xls',
                    'application/vnd.ms-excel',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                  ]}
                  onSelect={(list) => list && acceptSheets(Array.from(list))}
                >
                  <Button className="flex cursor-pointer flex-col items-center gap-2 bg-transparent outline-none">
                    <RiUploadCloud2Line size={24} className="shrink-0 text-[#71717a]" />
                    <div className="flex flex-col items-center">
                      <Text slot="label" className="text-base font-medium leading-7 text-[#18181b]">
                        Загрузите инженеров
                      </Text>
                      <span className="text-xs leading-5 text-[#71717a]">
                        Нажмите на это поле или перетащите
                        <br />в него excel или csv файл
                      </span>
                    </div>
                  </Button>
                </FileTrigger>
              </DropZone>
            )}
          </div>

          <div className="flex shrink-0 px-5 pt-2 pb-5">
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-[#dedee0] bg-white text-sm font-medium leading-5 text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
              style={{ borderRadius: 8, padding: '8px 16px' }}
            >
              Отмена
            </button>
          </div>
        </>
      )}
    </AppPanel>
  )
}
