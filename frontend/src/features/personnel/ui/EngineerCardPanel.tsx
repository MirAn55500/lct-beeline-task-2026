import { Fragment, type ReactNode } from 'react'
import { RiCloseLine, RiPencilLine } from '@remixicon/react'

import {
  QUALIFICATION_HINT,
  TRANSPORT_LABEL,
  type PersonnelEngineer,
} from '@/features/personnel/mocks'
import { WORK_TYPE_OPTIONS } from '@/features/tickets'
import { getInitials } from '@/shared/lib/text'
import { AppPanel } from '@/shared/ui'

import { describeWeekdays } from '../lib/weekdays'
import { TRANSPORT_ICON } from './transportIcons'

// Навыки — виды работ из заявок, как в форме: подключение открывает и дозаказы
const WORK_TYPE_SKILL: Record<string, string> = {
  'Аварийные работы': 'emergency',
  Подключение: 'connection',
  Ремонт: 'local',
  Дозаказ: 'connection',
}

function formatWorkDay(start?: string | null, end?: string | null) {
  if (!start || !end) return null
  // «09:00:00» → «9:00», как в макете
  const trim = (value: string) => value.slice(0, 5).replace(/^0(\d)/, '$1')
  return `${trim(start)}–${trim(end)}`
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs leading-5 text-muted">{label}</span>
      <div className="text-sm font-medium leading-6 text-foreground">{children}</div>
    </div>
  )
}

function Note({ children }: { children: ReactNode }) {
  return <span className="block text-xs font-normal leading-5 text-muted">{children}</span>
}

function Tag({ children }: { children: ReactNode }) {
  return (
    <span
      className="inline-flex h-6 items-center gap-1 bg-surface-tertiary px-1.5 text-sm font-medium leading-6 text-foreground"
      style={{ borderRadius: 4 }}
    >
      {children}
    </span>
  )
}

type EngineerCardPanelProps = {
  engineer: PersonnelEngineer
  onClose: () => void
  onEdit?: () => void
}

/** Правая панель «Карточка Инженера». */
export function EngineerCardPanel({ engineer, onClose, onEdit }: EngineerCardPanelProps) {
  const TransportIcon = TRANSPORT_ICON[engineer.transport]
  const workDay = formatWorkDay(engineer.startWork, engineer.endWork)
  const schedule = describeWeekdays(engineer.workDays)
  const workTypes = WORK_TYPE_OPTIONS.filter((type) =>
    (engineer.skills as string[]).includes(WORK_TYPE_SKILL[type]!),
  )
  const qualificationHint =
    engineer.qualificationHint ??
    (engineer.qualification ? QUALIFICATION_HINT[engineer.qualification] : null)

  const fields: { label: string; value: ReactNode }[] = [
    {
      label: 'Домашний адрес',
      value: engineer.homeAddress ?? <span className="font-normal text-muted">Не указан</span>,
    },
    {
      label: 'Доступный транспорт',
      value: (
        <span className="flex flex-wrap gap-1">
          <Tag>
            {TransportIcon ? <TransportIcon size={14} className="shrink-0 text-muted" /> : null}
            {TRANSPORT_LABEL[engineer.transport] ?? engineer.transport}
          </Tag>
        </span>
      ),
    },
    {
      label: 'Квалификация',
      value: engineer.position ? (
        <>
          {engineer.position}
          {qualificationHint ? <Note>{qualificationHint}</Note> : null}
        </>
      ) : (
        <span className="font-normal text-muted">Не указана</span>
      ),
    },
    {
      label: 'Навыки',
      value:
        workTypes.length > 0 ? (
          <span className="flex flex-wrap gap-1">
            {workTypes.map((type) => (
              <Tag key={type}>{type}</Tag>
            ))}
          </span>
        ) : (
          <span className="font-normal text-muted">Нет навыков</span>
        ),
    },
    { label: 'Бригада', value: engineer.brigadeName ?? '—' },
    {
      label: 'Рабочий график',
      value: (
        <>
          {schedule.work}
          <Note>
            {[schedule.off, engineer.ownWorkDays ? 'свой график' : 'как у бригады']
              .filter(Boolean)
              .join(' · ')}
          </Note>
        </>
      ),
    },
    {
      label: 'Рабочий день',
      value: workDay ? (
        <>
          {workDay}
          <Note>{engineer.ownSchedule ? 'Своя смена' : 'Как у бригады'}</Note>
        </>
      ) : (
        '—'
      ),
    },
  ]

  return (
    <AppPanel className="flex min-h-0 w-[346px] shrink-0 flex-col">
      <div className="relative flex shrink-0 flex-col px-5 pt-5 pr-12 pb-2">
        <h2 className="text-xl font-semibold leading-7 text-foreground">Карточка Инженера</h2>
        <button
          type="button"
          aria-label="Закрыть"
          onClick={onClose}
          className="absolute top-4 right-4 flex size-8 cursor-pointer items-center justify-center text-muted transition-colors hover:bg-surface-hover"
          style={{ borderRadius: 8 }}
        >
          <RiCloseLine size={16} />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-5 py-3">
        <div className="flex items-center gap-3">
          <span
            className="flex size-8 shrink-0 items-center justify-center bg-surface-tertiary text-xs font-medium leading-5 text-foreground"
            style={{ borderRadius: 8 }}
          >
            {getInitials(engineer.name)}
          </span>
          <span className="min-w-0 text-sm font-medium leading-6 break-words text-foreground">
            {engineer.name}
          </span>
        </div>

        {fields.map(({ label, value }) => (
          <Fragment key={label}>
            <div className="h-px w-full shrink-0 bg-border" />
            <Field label={label}>{value}</Field>
          </Fragment>
        ))}
      </div>

      {onEdit ? (
        <div className="shrink-0 px-5 pt-2 pb-5">
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex h-9 w-full cursor-pointer items-center justify-center gap-2 border border-border bg-surface text-sm font-medium leading-5 text-foreground transition-colors hover:bg-surface-hover"
            style={{ borderRadius: 8, padding: '8px 16px' }}
          >
            <RiPencilLine size={16} className="shrink-0" />
            Редактировать
          </button>
        </div>
      ) : null}
    </AppPanel>
  )
}
