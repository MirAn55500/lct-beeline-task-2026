import { useRef, useState, type SetStateAction } from 'react'
import { ListBox, ScrollShadow, Select, toast } from '@heroui/react'
import { Time } from '@internationalized/date'
import {
  RiArrowDownSLine,
  RiDeleteBinLine,
  RiDownload2Line,
  RiFileTextLine,
  RiLoopRightLine,
  RiUploadCloud2Line,
} from '@remixicon/react'
import { DropZone, FileTrigger, Button as AriaButton, isFileDropItem } from 'react-aria-components'

import {
  useCreateEngineerMutation,
  useUpdateEngineerMutation,
  useUploadEngineersMutation,
} from '@/features/personnel/api'
import {
  QUALIFICATION_HINT,
  QUALIFICATION_LABEL,
  TRANSPORT_LABEL,
  type SkillCode,
  type TransportCode,
} from '@/features/personnel/mocks'
import type {
  EngineerBody,
  LunchPlace,
  PersonnelBrigade,
  PersonnelEngineer,
  QualificationCode,
} from '@/features/personnel/types'
import { WORK_TYPE_OPTIONS } from '@/features/tickets'
import { cn } from '@/shared/lib/cn'
import { pluralRu } from '@/shared/lib/text'
import { AppPanel } from '@/shared/ui'

import { errorReason } from '../lib/errors'
import { lunchPlaceNote, lunchSpotMissing, lunchTimeError, type LunchDraft } from '../lib/lunch'
import {
  ENGINEERS_FILE_TYPES,
  ENGINEERS_TEMPLATE_SIZE,
  downloadEngineersTemplate,
  formatFileSize,
  isEngineersFile,
} from '../lib/template'
import { formatTime, parseTime } from '../lib/time'
import { WEEKDAYS, sameDays } from '../lib/weekdays'
import type { AddressPoint } from './AddressPointField'
import { FieldLabel, Hint, TextInput, ToggleChip, WorkTimeField } from './formParts'
import { LunchFields } from './LunchFields'
import { TRANSPORT_ICON } from './transportIcons'

const TRANSPORT_ORDER: TransportCode[] = ['car', 'public', 'bike', 'walking']

const QUALIFICATION_ORDER: QualificationCode[] = ['master', 'worker', 'novice']

const WORK_TYPE_TO_SKILL: Record<string, SkillCode> = {
  'Аварийные работы': 'emergency',
  Подключение: 'connection',
  Дозаказ: 'connection',
  Ремонт: 'local',
}

function workTypesOf(skills: SkillCode[]): string[] {
  return WORK_TYPE_OPTIONS.filter((type) => skills.includes(WORK_TYPE_TO_SKILL[type]!))
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

function toggleIn<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((entry) => entry !== item) : [...list, item]
}

/** Рабочий день, дни и обед бригады — смена, график и обед инженера по умолчанию. */
function brigadeSchedule(brigades: PersonnelBrigade[], brigadeId: number | null) {
  const brigade = brigades.find((item) => item.id === brigadeId)
  return {
    timeFrom: parseTime(brigade?.startWork) ?? new Time(9, 0),
    timeTo: parseTime(brigade?.endWork) ?? new Time(18, 0),
    workDays: brigade?.workDays.length ? brigade.workDays : [1, 2, 3, 4, 5, 6, 7],
    lunchFrom: parseTime(brigade?.lunchStart) ?? new Time(13, 0),
    lunchTo: parseTime(brigade?.lunchEnd) ?? new Time(14, 0),
    lunchPlace: brigade?.lunchPlace ?? ('last_request' as LunchPlace),
    lunchSpot: spotOf(brigade?.lunchAddress, brigade?.lunchPoint),
  }
}

function spotOf(
  address: string | null | undefined,
  point: [number, number] | null | undefined,
): AddressPoint {
  return { address: address ?? '', point: point ?? null, confirmed: point != null }
}

type Draft = {
  name: string
  homeAddress: string
  transport: TransportCode | null
  qualification: QualificationCode | null
  workTypes: string[]
  brigadeId: number | null
  timeFrom: Time | null
  timeTo: Time | null
  workDays: number[]
  lunchFrom: Time | null
  lunchTo: Time | null
  lunchPlace: LunchPlace
  lunchSpot: AddressPoint
}

function initialDraft(engineer: PersonnelEngineer | undefined): Draft {
  if (!engineer) {
    return {
      name: '',
      homeAddress: '',
      transport: null,
      qualification: null,
      workTypes: [],
      brigadeId: null,
      timeFrom: null,
      timeTo: null,
      workDays: [],
      lunchFrom: null,
      lunchTo: null,
      lunchPlace: 'last_request',
      lunchSpot: spotOf(null, null),
    }
  }
  return {
    name: engineer.name,
    homeAddress: engineer.homeAddress ?? '',
    transport: engineer.transport,
    qualification: engineer.qualification ?? null,
    workTypes: workTypesOf(engineer.skills),
    brigadeId: engineer.brigadeId,
    timeFrom: parseTime(engineer.startWork),
    timeTo: parseTime(engineer.endWork),
    workDays: engineer.workDays,
    lunchFrom: parseTime(engineer.lunchStart),
    lunchTo: parseTime(engineer.lunchEnd),
    lunchPlace: engineer.lunchPlace,
    lunchSpot: spotOf(engineer.lunchAddress, engineer.lunchPoint),
  }
}

/** Место обеда для тела запроса: своя точка — с адресом и координатами. */
function lunchPlaceBody(snapshot: Draft): Partial<EngineerBody> {
  if (snapshot.lunchPlace !== 'point') return { lunch_place: snapshot.lunchPlace }
  const point = snapshot.lunchSpot.point
  if (point == null) return {}
  return {
    lunch_place: 'point',
    lunch_address: snapshot.lunchSpot.address.trim(),
    lunch_lon: point[0],
    lunch_lat: point[1],
  }
}

type EngineerFormPanelProps = {
  brigades: PersonnelBrigade[]
  defaultBrigadeId: number | null
  /** Инженер, которого редактируют; без него — добавление (файл или один). */
  engineer?: PersonnelEngineer
  /** Сразу форма одного инженера, без зоны файла. */
  startInSingle?: boolean
  onAdd?: (added: PersonnelEngineer[]) => void
  onSaved?: (saved: PersonnelEngineer) => void
  onClose: () => void
}

/** Правая панель: загрузка файла / один инженер / редактирование. */
export function EngineerFormPanel({
  brigades,
  defaultBrigadeId,
  engineer,
  startInSingle = false,
  onAdd,
  onSaved,
  onClose,
}: EngineerFormPanelProps) {
  const editing = engineer != null
  const [mode, setMode] = useState<'file' | 'single'>(
    editing || startInSingle ? 'single' : 'file',
  )
  const [submitting, setSubmitting] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [uploadBrigadeId, setUploadBrigadeId] = useState<number | null>(defaultBrigadeId)
  const [createEngineer] = useCreateEngineerMutation()
  const [updateEngineer] = useUpdateEngineerMutation()
  const [uploadEngineers] = useUploadEngineersMutation()
  const [draft, setDraft] = useState<Draft>(() => initialDraft(engineer))
  const [hoursTouched, setHoursTouched] = useState(engineer?.ownSchedule ?? false)
  const [daysTouched, setDaysTouched] = useState(engineer?.ownWorkDays ?? false)
  // Обед тоже идёт за бригадой — окно и место по отдельности, как часы и дни
  const [lunchTimeTouched, setLunchTimeTouched] = useState(engineer?.ownLunchTime ?? false)
  const [lunchPlaceTouched, setLunchPlaceTouched] = useState(engineer?.ownLunchPlace ?? false)
  // Своя точка обеда уже в черновике: адрес по точке приходит позже, из старого замыкания
  const lunchSpotSeeded = useRef(engineer?.ownLunchPlace ?? false)

  const brigadeId = draft.brigadeId ?? defaultBrigadeId
  const brigadeDefaults = brigadeSchedule(brigades, brigadeId)
  const form: Draft = {
    ...draft,
    brigadeId,
    ...(hoursTouched
      ? {}
      : { timeFrom: brigadeDefaults.timeFrom, timeTo: brigadeDefaults.timeTo }),
    workDays: daysTouched ? draft.workDays : brigadeDefaults.workDays,
    ...(lunchTimeTouched
      ? {}
      : { lunchFrom: brigadeDefaults.lunchFrom, lunchTo: brigadeDefaults.lunchTo }),
    ...(lunchPlaceTouched
      ? {}
      : { lunchPlace: brigadeDefaults.lunchPlace, lunchSpot: brigadeDefaults.lunchSpot }),
  }
  const ownLunchTime =
    lunchTimeTouched &&
    (form.lunchFrom?.compare(brigadeDefaults.lunchFrom) !== 0 ||
      form.lunchTo?.compare(brigadeDefaults.lunchTo) !== 0)
  const ownLunchPlace =
    lunchPlaceTouched &&
    (form.lunchPlace !== brigadeDefaults.lunchPlace ||
      (form.lunchPlace === 'point' &&
        (form.lunchSpot.point?.join() !== brigadeDefaults.lunchSpot.point?.join() ||
          form.lunchSpot.address.trim() !== brigadeDefaults.lunchSpot.address.trim())))
  const lunch: LunchDraft = {
    timeFrom: form.lunchFrom,
    timeTo: form.lunchTo,
    place: form.lunchPlace,
    spot: form.lunchSpot,
  }
  // Своё окно обязано помещаться в смену; окно бригады, которое в неё не помещается,
  // сохранить не мешает — в такой день инженер просто без обеда
  const lunchProblem = lunchTimeError(lunch, form.timeFrom, form.timeTo)
  const ownSchedule =
    hoursTouched &&
    (form.timeFrom?.compare(brigadeDefaults.timeFrom) !== 0 ||
      form.timeTo?.compare(brigadeDefaults.timeTo) !== 0)
  const ownDays = daysTouched && !sameDays(form.workDays, brigadeDefaults.workDays)

  const patch = (next: Partial<Draft>) => setDraft((prev) => ({ ...prev, ...next }))
  const setHours = (next: Partial<Pick<Draft, 'timeFrom' | 'timeTo'>>) => {
    setHoursTouched(true)
    setDraft((prev) => ({ ...prev, timeFrom: form.timeFrom, timeTo: form.timeTo, ...next }))
  }
  const setLunchTime = (next: Partial<Pick<LunchDraft, 'timeFrom' | 'timeTo'>>) => {
    setLunchTimeTouched(true)
    setDraft((prev) => ({
      ...prev,
      lunchFrom: 'timeFrom' in next ? (next.timeFrom ?? null) : form.lunchFrom,
      lunchTo: 'timeTo' in next ? (next.timeTo ?? null) : form.lunchTo,
    }))
  }
  const setLunchPlace = (lunchPlace: LunchPlace) => {
    setLunchPlaceTouched(true)
    const seeded = lunchSpotSeeded.current
    lunchSpotSeeded.current = true
    const brigadeSpot = form.lunchSpot
    setDraft((prev) => ({ ...prev, lunchPlace, lunchSpot: seeded ? prev.lunchSpot : brigadeSpot }))
  }
  // Адрес по точке приходит позже — обновление функциональное
  const setLunchSpot = (action: SetStateAction<AddressPoint>) => {
    setLunchPlaceTouched(true)
    const seeded = lunchSpotSeeded.current
    lunchSpotSeeded.current = true
    const brigadeSpot = form.lunchSpot
    setDraft((prev) => {
      const base = seeded ? prev.lunchSpot : brigadeSpot
      return { ...prev, lunchSpot: typeof action === 'function' ? action(base) : action }
    })
  }
  const toggleDay = (day: number) => {
    setDaysTouched(true)
    setDraft((prev) => ({ ...prev, workDays: toggleIn(form.workDays, day).sort() }))
  }

  const hoursValid =
    form.timeFrom != null && form.timeTo != null && form.timeTo.compare(form.timeFrom) > 0

  const isValid =
    form.name.trim() !== '' &&
    form.transport != null &&
    form.qualification != null &&
    form.workTypes.length > 0 &&
    form.brigadeId != null &&
    form.workDays.length > 0 &&
    hoursValid &&
    (!ownLunchTime || lunchProblem == null) &&
    (form.lunchFrom != null && form.lunchTo != null) &&
    !(lunchPlaceTouched && lunchSpotMissing(lunch))

  const bodyOf = (
    snapshot: Draft,
    own: { hours: boolean; days: boolean; lunchTime: boolean; lunchPlace: boolean },
  ): EngineerBody | null => {
    if (
      snapshot.brigadeId == null ||
      snapshot.transport == null ||
      snapshot.timeFrom == null ||
      snapshot.timeTo == null
    ) {
      return null
    }
    return {
      name: snapshot.name.trim(),
      brigade_id: snapshot.brigadeId,
      transport: snapshot.transport,
      qualification: snapshot.qualification ?? undefined,
      skills: [...new Set(snapshot.workTypes.map((type) => WORK_TYPE_TO_SKILL[type]!))],
      home_address: snapshot.homeAddress.trim() || null,
      ...(own.hours
        ? { start_work: formatTime(snapshot.timeFrom), end_work: formatTime(snapshot.timeTo) }
        : {}),
      ...(own.days ? { work_days: snapshot.workDays } : {}),
      // Обед бригады тоже не передаём — тогда он меняется вместе с ней
      ...(own.lunchTime && snapshot.lunchFrom && snapshot.lunchTo
        ? { lunch_start: formatTime(snapshot.lunchFrom), lunch_end: formatTime(snapshot.lunchTo) }
        : {}),
      ...(own.lunchPlace ? lunchPlaceBody(snapshot) : {}),
    }
  }

  const own = {
    hours: ownSchedule,
    days: ownDays,
    lunchTime: ownLunchTime,
    lunchPlace: ownLunchPlace,
  }
  const body = bodyOf(form, own)
  const [initialBody] = useState(() => JSON.stringify(body))
  const dirty = !editing || JSON.stringify(body) !== initialBody

  const pickFile = (files: File[]) => {
    const next = files.find(isEngineersFile)
    if (next) setFile(next)
  }

  const submitFile = async () => {
    if (uploadBrigadeId == null || file == null) return
    setSubmitting(true)
    try {
      const result = await uploadEngineers({ file, brigadeId: uploadBrigadeId }).unwrap()
      if (result.created === 0) {
        toast.danger('Инженеры не добавлены', {
          description:
            result.skipped > 0
              ? `Пропущено строк: ${result.skipped}. Проверьте формат файла.`
              : 'В файле нет подходящих строк',
        })
        return
      }
      toast.success(
        `Добавлено ${result.created} ${pluralRu(result.created, ['инженер', 'инженера', 'инженеров'])}`,
        {
          description:
            result.skipped > 0 ? `Пропущено строк: ${result.skipped}` : undefined,
        },
      )
      onAdd?.(result.engineers)
      onClose()
    } catch (error) {
      toast.danger('Файл не загружен', {
        description: errorReason(error),
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => void submitFile(),
        },
      })
    } finally {
      setSubmitting(false)
    }
  }

  const submit = async (payload: EngineerBody) => {
    setSubmitting(true)
    try {
      if (engineer) {
        const saved = await updateEngineer({ id: engineer.id, body: payload }).unwrap()
        toast.success('Сведения об инженере обновлены')
        onSaved?.(saved)
      } else {
        const created = await createEngineer(payload).unwrap()
        toast.success('Инженер добавлен')
        onAdd?.([created])
        onClose()
      }
    } catch (error) {
      toast.danger(editing ? 'Сведения об инженере не обновлены' : 'Инженер не добавлен', {
        description: errorReason(error),
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => void submit(payload),
        },
      })
    } finally {
      setSubmitting(false)
    }
  }

  const qualificationHint =
    form.qualification != null ? QUALIFICATION_HINT[form.qualification] : null

  const canUpload = uploadBrigadeId != null && file != null && !submitting

  if (!editing && mode === 'file') {
    return (
      <AppPanel className="flex min-h-0 w-[346px] shrink-0 flex-col">
        <div className="flex shrink-0 flex-col gap-1 px-5 pt-5 pb-2">
          <h2 className="text-xl font-semibold leading-7 text-foreground">Загрузить инженеров</h2>
          <p className="text-sm leading-6 text-muted">
            Новые инженеры будут добавлены в выбранную бригаду.
            <span className="mt-2 block">
              Чтобы добавить одного{' '}
              <button
                type="button"
                onClick={() => setMode('single')}
                className="cursor-pointer text-link outline-none hover:underline focus-visible:underline"
              >
                Нажмите здесь
              </button>
            </span>
          </p>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-4 px-5 py-3">
          <div className="flex flex-col gap-1">
            <FieldLabel required>Бригада</FieldLabel>
            <SingleSelect
              label="Бригада"
              placeholder="Выберите бригаду"
              options={brigades.map((item) => ({ id: item.id, label: item.name }))}
              value={uploadBrigadeId}
              onChange={setUploadBrigadeId}
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
                  <span className="truncate text-xs leading-5 font-medium text-foreground">
                    {file.name}
                  </span>
                  <span className="text-xs leading-4 text-muted">{formatFileSize(file.size)}</span>
                </div>
                <FileTrigger
                  acceptedFileTypes={ENGINEERS_FILE_TYPES}
                  onSelect={(list) => list && pickFile(Array.from(list))}
                >
                  <AriaButton
                    aria-label="Заменить файл"
                    className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[8px] bg-surface-tertiary text-foreground outline-none transition-colors hover:bg-default-hover"
                  >
                    <RiLoopRightLine size={16} />
                  </AriaButton>
                </FileTrigger>
                <button
                  type="button"
                  aria-label="Удалить файл"
                  onClick={() => setFile(null)}
                  className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[8px] bg-surface-tertiary text-foreground transition-colors hover:bg-default-hover"
                >
                  <RiDeleteBinLine size={16} />
                </button>
              </div>
            ) : (
              <DropZone
                getDropOperation={(types) =>
                  types.has('text/csv') ||
                  types.has('application/json') ||
                  types.has('text/plain')
                    ? 'copy'
                    : 'cancel'
                }
                onDrop={async (event) => {
                  const files: File[] = []
                  for (const item of event.items) {
                    if (isFileDropItem(item)) files.push(await item.getFile())
                  }
                  pickFile(files)
                }}
                className="flex min-h-[160px] flex-col items-center justify-center rounded-[8px] border border-dashed border-border bg-surface-tertiary/40 px-4 py-6 outline-none data-[drop-target]:border-accent data-[drop-target]:bg-accent/5"
              >
                <FileTrigger
                  acceptedFileTypes={ENGINEERS_FILE_TYPES}
                  onSelect={(list) => list && pickFile(Array.from(list))}
                >
                  <AriaButton className="flex cursor-pointer flex-col items-center gap-3 outline-none">
                    <RiUploadCloud2Line size={28} className="shrink-0 text-muted" />
                    <div className="flex flex-col items-center text-center">
                      <span className="text-sm font-medium leading-5 text-foreground">
                        Загрузите инженеров
                      </span>
                      <span className="text-xs leading-5 text-muted">
                        Нажмите на это поле или перетащите
                        <br />в него json или csv файл
                      </span>
                    </div>
                  </AriaButton>
                </FileTrigger>
              </DropZone>
            )}
          </div>

          <button
            type="button"
            onClick={downloadEngineersTemplate}
            className="flex h-9 cursor-pointer items-center justify-center gap-2 self-start text-sm leading-5 font-medium text-foreground transition-colors hover:text-link"
          >
            <RiDownload2Line size={16} />
            Скачать шаблон ({ENGINEERS_TEMPLATE_SIZE})
          </button>
        </div>

        <div className="flex shrink-0 gap-2 px-5 pt-2 pb-5">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-border bg-surface text-sm font-medium leading-5 text-foreground transition-colors hover:bg-surface-hover"
            style={{ borderRadius: 8, padding: '8px 16px' }}
          >
            Отмена
          </button>
          <button
            type="button"
            disabled={!canUpload}
            onClick={() => void submitFile()}
            className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center bg-accent text-sm font-medium leading-5 text-accent-foreground transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent"
            style={{ borderRadius: 8, padding: '8px 16px' }}
          >
            {submitting ? 'Загружаем…' : 'Загрузить'}
          </button>
        </div>
      </AppPanel>
    )
  }

  return (
    <AppPanel className="flex min-h-0 w-[346px] shrink-0 flex-col">
      <div className="flex shrink-0 flex-col gap-1 px-5 pt-5 pb-2">
        <h2 className="text-xl font-semibold leading-7 text-foreground">
          {editing ? 'Редактировать инженера' : 'Добавить инженера'}
        </h2>
        <p className="text-sm leading-6 text-muted">
          {editing ? (
            'Измените информацию о сотруднике'
          ) : (
            <>
              Заполните информацию о сотруднике.
              <span className="mt-2 block">
                Чтобы загрузить файл{' '}
                <button
                  type="button"
                  onClick={() => {
                    setMode('file')
                    setFile(null)
                  }}
                  className="cursor-pointer text-link outline-none hover:underline focus-visible:underline"
                >
                  Нажмите здесь
                </button>
              </span>
            </>
          )}
        </p>
      </div>

      <ScrollShadow hideScrollBar size={40} className="min-h-0 flex-1" orientation="vertical">
        <div className="flex flex-col gap-3 px-5 py-3">
          <label className="flex flex-col gap-1">
            <FieldLabel required>ФИО инженера</FieldLabel>
            <TextInput
              aria-label="ФИО инженера"
              value={draft.name}
              onChange={(name) => patch({ name })}
              placeholder="Введите ФИО"
              maxLength={200}
            />
          </label>

          <label className="flex flex-col gap-1">
            <FieldLabel>Домашний адрес</FieldLabel>
            <TextInput
              aria-label="Домашний адрес"
              value={draft.homeAddress}
              onChange={(homeAddress) => patch({ homeAddress })}
              placeholder="Введите адрес"
              maxLength={300}
            />
          </label>

          <div className="flex flex-col gap-1">
            <FieldLabel required>Доступный транспорт</FieldLabel>
            <div className="flex flex-wrap gap-1 pt-1">
              {TRANSPORT_ORDER.map((code) => {
                const Icon = TRANSPORT_ICON[code]
                return (
                  <ToggleChip
                    key={code}
                    active={draft.transport === code}
                    onToggle={() => patch({ transport: code })}
                  >
                    <Icon size={16} className="shrink-0" />
                    {TRANSPORT_LABEL[code]}
                  </ToggleChip>
                )
              })}
            </div>
            <Hint>Один вид — по нему строится маршрут</Hint>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel required>Квалификация</FieldLabel>
            <SingleSelect
              label="Квалификация"
              placeholder="Выберите квалификацию"
              options={QUALIFICATION_ORDER.map((code) => ({
                id: code,
                label: QUALIFICATION_LABEL[code],
              }))}
              value={form.qualification}
              onChange={(qualification) => patch({ qualification })}
            />
            {qualificationHint ? <Hint>{qualificationHint}</Hint> : null}
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel required>Навыки</FieldLabel>
            <div className="flex flex-wrap gap-1 pt-1">
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

          <div className="h-px w-full bg-border" />

          <div className="flex flex-col gap-1">
            <FieldLabel required>Бригада</FieldLabel>
            <SingleSelect
              label="Бригада"
              placeholder="Выберите бригаду"
              options={brigades.map((brigade) => ({ id: brigade.id, label: brigade.name }))}
              value={form.brigadeId}
              onChange={(next) => patch({ brigadeId: next })}
            />
            <Hint>Бригада определяет офис и рабочее время</Hint>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel required>Рабочий график</FieldLabel>
            <div className="flex gap-1 pt-1">
              {WEEKDAYS.map(({ day, label }) => (
                <ToggleChip
                  key={day}
                  active={form.workDays.includes(day)}
                  onToggle={() => toggleDay(day)}
                  className="!h-8 min-w-0 flex-1 justify-center !px-0"
                >
                  {label}
                </ToggleChip>
              ))}
            </div>
            {form.workDays.length === 0 ? (
              <p className="text-xs leading-5 text-danger">Выберите хотя бы один день</p>
            ) : (
              <Hint>
                {ownDays ? (
                  <>
                    Свой график — не меняется вместе с бригадой.{' '}
                    <button
                      type="button"
                      className="cursor-pointer text-accent hover:underline"
                      onClick={() => setDaysTouched(false)}
                    >
                      Как у бригады
                    </button>
                  </>
                ) : (
                  'Как у бригады — меняется вместе с ней'
                )}
              </Hint>
            )}
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel required>Рабочий день</FieldLabel>
            <div className="flex items-center">
              <WorkTimeField
                aria-label="Начало рабочего дня"
                value={form.timeFrom}
                onChange={(timeFrom) => setHours({ timeFrom })}
              />
              <span
                className="shrink-0 text-sm leading-5 text-muted"
                style={{ width: 12, textAlign: 'center' }}
              >
                -
              </span>
              <WorkTimeField
                aria-label="Конец рабочего дня"
                value={form.timeTo}
                onChange={(timeTo) => setHours({ timeTo })}
              />
            </div>
            {form.timeFrom == null || form.timeTo == null ? (
              <p className="text-xs leading-5 text-danger">Укажите начало и конец рабочего дня</p>
            ) : !hoursValid ? (
              <p className="text-xs leading-5 text-danger">Конец дня должен быть позже начала</p>
            ) : (
              <Hint>
                {ownSchedule ? (
                  <>
                    Своя смена — не меняется вместе с бригадой.{' '}
                    <button
                      type="button"
                      className="cursor-pointer text-accent hover:underline"
                      onClick={() => setHoursTouched(false)}
                    >
                      Как у бригады
                    </button>
                  </>
                ) : (
                  'Как у бригады — меняется вместе с ней'
                )}
              </Hint>
            )}
          </div>

          <LunchFields
            value={lunch}
            timeError={
              ownLunchTime || form.lunchFrom == null || form.lunchTo == null ? lunchProblem : null
            }
            onTime={setLunchTime}
            onPlace={setLunchPlace}
            onSpot={setLunchSpot}
            timeHint={
              ownLunchTime ? (
                <>
                  Свой обед — не меняется вместе с бригадой.{' '}
                  <button
                    type="button"
                    className="cursor-pointer text-accent hover:underline"
                    onClick={() => setLunchTimeTouched(false)}
                  >
                    Как у бригады
                  </button>
                </>
              ) : lunchProblem ? (
                'Обед бригады не помещается в эту смену — в такой день без обеда'
              ) : (
                'Как у бригады — час внутри окна поставит план'
              )
            }
            placeHint={
              ownLunchPlace ? (
                <>
                  {lunchPlaceNote(form.lunchPlace) ?? 'Своё место'} — не меняется вместе с бригадой.{' '}
                  <button
                    type="button"
                    className="cursor-pointer text-accent hover:underline"
                    onClick={() => {
                      setLunchPlaceTouched(false)
                      lunchSpotSeeded.current = false
                    }}
                  >
                    Как у бригады
                  </button>
                </>
              ) : (
                `Как у бригады${form.lunchPlace === 'point' ? '' : ` — ${lunchPlaceNote(form.lunchPlace)?.toLowerCase()}`}`
              )
            }
          />
        </div>
      </ScrollShadow>

      <div className="flex shrink-0 gap-2 px-5 pt-2 pb-5">
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-border bg-surface text-sm font-medium leading-5 text-foreground transition-colors hover:bg-surface-hover"
          style={{ borderRadius: 8, padding: '8px 16px' }}
        >
          Отмена
        </button>
        <button
          type="button"
          disabled={!isValid || !dirty || submitting || body == null}
          onClick={() => {
            if (body) void submit(body)
          }}
          className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center bg-accent text-sm font-medium leading-5 text-accent-foreground transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent"
          style={{ borderRadius: 8, padding: '8px 16px' }}
        >
          {submitting
            ? editing
              ? 'Сохраняем…'
              : 'Добавляем…'
            : editing
              ? 'Сохранить'
              : 'Добавить'}
        </button>
      </div>
    </AppPanel>
  )
}
