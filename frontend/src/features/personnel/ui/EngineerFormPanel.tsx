import { useState } from 'react'
import { ListBox, ScrollShadow, Select, toast } from '@heroui/react'
import { Time } from '@internationalized/date'
import { RiArrowDownSLine } from '@remixicon/react'

import { useCreateEngineerMutation, useUpdateEngineerMutation } from '@/features/personnel/api'
import {
  QUALIFICATION_HINT,
  QUALIFICATION_LABEL,
  TRANSPORT_LABEL,
  type SkillCode,
  type TransportCode,
} from '@/features/personnel/mocks'
import type {
  EngineerBody,
  PersonnelBrigade,
  PersonnelEngineer,
  QualificationCode,
} from '@/features/personnel/types'
import { WORK_TYPE_OPTIONS } from '@/features/tickets'
import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import { errorReason } from '../lib/errors'
import { formatTime, parseTime } from '../lib/time'
import { WEEKDAYS, sameDays } from '../lib/weekdays'
import { FieldLabel, Hint, TextInput, ToggleChip, WorkTimeField } from './formParts'
import { TRANSPORT_ICON } from './transportIcons'

const TRANSPORT_ORDER: TransportCode[] = ['car', 'public', 'bike', 'walking']

const QUALIFICATION_ORDER: QualificationCode[] = ['master', 'worker', 'novice']

// Навыки в форме — виды работ из заявок; в таблице они сведены в три группы.
const WORK_TYPE_TO_SKILL: Record<string, SkillCode> = {
  'Аварийные работы': 'emergency',
  Подключение: 'connection',
  Дозаказ: 'connection',
  Ремонт: 'local',
}

/** Навыки инженера → виды работ формы: подключение открывает и дозаказы. */
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

/** Рабочий день и дни бригады — смена и график инженера по умолчанию. */
function brigadeSchedule(brigades: PersonnelBrigade[], brigadeId: number | null) {
  const brigade = brigades.find((item) => item.id === brigadeId)
  return {
    timeFrom: parseTime(brigade?.startWork) ?? new Time(9, 0),
    timeTo: parseTime(brigade?.endWork) ?? new Time(18, 0),
    workDays: brigade?.workDays.length ? brigade.workDays : [1, 2, 3, 4, 5, 6, 7],
  }
}

type Draft = {
  name: string
  homeAddress: string
  transport: TransportCode | null
  qualification: QualificationCode | null
  workTypes: string[]
  /** null — бригада, открытая слева (только при добавлении). */
  brigadeId: number | null
  timeFrom: Time | null
  timeTo: Time | null
  workDays: number[]
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
  }
}

type EngineerFormPanelProps = {
  brigades: PersonnelBrigade[]
  defaultBrigadeId: number | null
  /** Инженер, которого редактируют; без него — добавление нового. */
  engineer?: PersonnelEngineer
  onAdd?: (added: PersonnelEngineer[]) => void
  onSaved?: (saved: PersonnelEngineer) => void
  onClose: () => void
}

/** Правая панель «Добавить инженера» / «Редактировать инженера». */
export function EngineerFormPanel({
  brigades,
  defaultBrigadeId,
  engineer,
  onAdd,
  onSaved,
  onClose,
}: EngineerFormPanelProps) {
  const editing = engineer != null
  const [submitting, setSubmitting] = useState(false)
  const [createEngineer] = useCreateEngineerMutation()
  const [updateEngineer] = useUpdateEngineerMutation()
  const [draft, setDraft] = useState<Draft>(() => initialDraft(engineer))
  // Часы и дни идут за бригадой, пока их не поменяли руками: у нового инженера сразу,
  // у сохранённого — если у него не своя смена или не свой график
  const [hoursTouched, setHoursTouched] = useState(engineer?.ownSchedule ?? false)
  const [daysTouched, setDaysTouched] = useState(engineer?.ownWorkDays ?? false)

  const brigadeId = draft.brigadeId ?? defaultBrigadeId
  const brigadeDefaults = brigadeSchedule(brigades, brigadeId)
  const form: Draft = {
    ...draft,
    brigadeId,
    ...(hoursTouched
      ? {}
      : { timeFrom: brigadeDefaults.timeFrom, timeTo: brigadeDefaults.timeTo }),
    workDays: daysTouched ? draft.workDays : brigadeDefaults.workDays,
  }
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
    hoursValid

  const bodyOf = (snapshot: Draft, own: { hours: boolean; days: boolean }): EngineerBody | null => {
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
      // Часы и дни бригады не передаём: тогда они меняются вместе с бригадой
      ...(own.hours
        ? { start_work: formatTime(snapshot.timeFrom), end_work: formatTime(snapshot.timeTo) }
        : {}),
      ...(own.days ? { work_days: snapshot.workDays } : {}),
    }
  }

  const own = { hours: ownSchedule, days: ownDays }
  const body = bodyOf(form, own)
  // Сохранять нечего, пока карточка совпадает с тем, что пришло с сервера
  const [initialBody] = useState(() => JSON.stringify(body))
  const dirty = !editing || JSON.stringify(body) !== initialBody

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

  return (
    <AppPanel className="flex min-h-0 w-[346px] shrink-0 flex-col">
      <div className="flex shrink-0 flex-col gap-1 px-5 pt-5 pb-2">
        <h2 className="text-xl font-semibold leading-7 text-foreground">
          {editing ? 'Редактировать инженера' : 'Добавить инженера'}
        </h2>
        <p className="text-sm leading-6 text-muted">
          {editing ? 'Измените информацию о сотруднике' : 'Заполните информацию о сотруднике'}
        </p>
      </div>

      <ScrollShadow
        hideScrollBar
        size={40}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
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
