import { useState, type ReactNode } from 'react'
import { ListBox, ScrollShadow, Select, TimeField, toast } from '@heroui/react'
import { Time } from '@internationalized/date'
import { RiArrowDownSLine, RiTimeLine } from '@remixicon/react'

import { useCreateEngineerMutation } from '@/features/personnel/api'
import {
  TRANSPORT_LABEL,
  type SkillCode,
  type TransportCode,
} from '@/features/personnel/mocks'
import type { PersonnelBrigade, PersonnelEngineer } from '@/features/personnel/types'
import { WORK_TYPE_OPTIONS } from '@/features/tickets'
import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import { TRANSPORT_ICON } from './transportIcons'

const TRANSPORT_ORDER: TransportCode[] = ['car', 'public', 'bike', 'walking']

// Навыки в форме — виды работ из заявок; в таблице они сведены в три группы.
const WORK_TYPE_TO_SKILL: Record<string, SkillCode> = {
  'Аварийные работы': 'emergency',
  Подключение: 'connection',
  Дозаказ: 'connection',
  Ремонт: 'local',
}

function formatTime(value: Time): string {
  return `${String(value.hour).padStart(2, '0')}:${String(value.minute).padStart(2, '0')}:00`
}

function FieldLabel({ children, required }: { children: ReactNode; required?: boolean }) {
  return (
    <span className="text-sm font-medium leading-6 text-foreground">
      {children}
      {required ? <span className="ms-1 text-danger">*</span> : null}
    </span>
  )
}

function Hint({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-5 text-muted">{children}</p>
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
          ? 'bg-accent text-accent-foreground hover:bg-accent-hover'
          : 'bg-surface-tertiary text-foreground hover:bg-default-hover',
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
      className="h-9 w-full border border-border bg-surface px-3 text-sm leading-5 text-foreground outline-none placeholder:text-muted focus-visible:border-focus"
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
        className="flex h-9 w-full items-center border border-border bg-surface shadow-none"
        style={{ borderRadius: 8, paddingLeft: 12, paddingRight: 12 }}
      >
        <TimeField.Input className="min-w-0 flex-1 text-sm leading-5 text-foreground">
          {(segment) => <TimeField.Segment segment={segment} />}
        </TimeField.Input>
        <TimeField.Suffix className="ms-2">
          <RiTimeLine size={16} className="text-muted" />
        </TimeField.Suffix>
      </TimeField.Group>
    </TimeField>
  )
}

function toggleIn<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((entry) => entry !== item) : [...list, item]
}

type ManualDraft = {
  name: string
  transports: TransportCode[]
  workTypes: string[]
  brigadeId: number | null
  timeFrom: Time | null
  timeTo: Time | null
}

type AddEngineerPanelProps = {
  brigades: PersonnelBrigade[]
  defaultBrigadeId: number | null
  /** @deprecated оставлен для совместимости вызова */
  engineers?: PersonnelEngineer[]
  onAdd: (added: PersonnelEngineer[]) => void
  onClose: () => void
}

export function AddEngineerPanel({
  brigades,
  defaultBrigadeId,
  onAdd,
  onClose,
}: AddEngineerPanelProps) {
  const [submitting, setSubmitting] = useState(false)
  const [createEngineer] = useCreateEngineerMutation()
  const [draft, setDraft] = useState<ManualDraft>(() => ({
    name: '',
    transports: [],
    workTypes: [],
    brigadeId: defaultBrigadeId,
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

  return (
    <AppPanel className="flex min-h-0 w-[346px] shrink-0 flex-col">
      <div className="flex shrink-0 flex-col gap-1 px-5 pt-5">
        <h2 className="text-xl font-semibold leading-7 text-foreground">Добавить инженера</h2>
        <p className="text-sm leading-6 text-muted">Заполните информацию о сотруднике</p>
      </div>

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

          <div className="h-px w-full bg-border" />

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

          <div className="flex flex-col gap-1">
            <FieldLabel required>Рабочий день</FieldLabel>
            <div className="flex items-center">
              <WorkTimeField
                aria-label="Начало рабочего дня"
                value={draft.timeFrom}
                onChange={(timeFrom) => patch({ timeFrom })}
              />
              <span
                className="shrink-0 text-sm leading-5 text-muted"
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
          className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-border bg-surface text-sm font-medium leading-5 text-foreground transition-colors hover:bg-surface-hover"
          style={{ borderRadius: 8, padding: '8px 16px' }}
        >
          Отмена
        </button>
        <button
          type="button"
          disabled={!isValid || submitting}
          onClick={() => void submitManual(draft)}
          className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center bg-accent text-sm font-medium leading-5 text-accent-foreground transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent"
          style={{ borderRadius: 8, padding: '8px 16px' }}
        >
          {submitting ? 'Добавляем…' : 'Добавить'}
        </button>
      </div>
    </AppPanel>
  )
}
