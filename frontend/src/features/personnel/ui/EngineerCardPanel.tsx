import type { ReactNode } from 'react'
import { RiCloseLine, RiVipCrown2Fill } from '@remixicon/react'

import {
  SKILL_LABEL,
  TRANSPORT_LABEL,
  type PersonnelEngineer,
} from '@/features/personnel/mocks'
import { getInitials } from '@/shared/lib/text'
import { AppPanel } from '@/shared/ui'

import { TRANSPORT_ICON } from './transportIcons'

function formatWorkDay(start?: string | null, end?: string | null) {
  if (!start || !end) return null
  const trim = (value: string) => value.slice(0, 5)
  return `${trim(start)}–${trim(end)}`
}

function Field({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium leading-5 text-[#71717a]">{label}</span>
      <div className="text-sm leading-6 text-[#18181b]">{children}</div>
    </div>
  )
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span
      className="inline-flex h-7 items-center bg-[#ebebec] px-2.5 text-sm font-medium leading-5 text-[#18181b]"
      style={{ borderRadius: 8 }}
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

/** Правая панель «Карточка Инженера» — только поля, которые есть в API/БД. */
export function EngineerCardPanel({
  engineer,
  onClose,
  onEdit,
}: EngineerCardPanelProps) {
  const TransportIcon = TRANSPORT_ICON[engineer.transport]
  const workDay = formatWorkDay(engineer.startWork, engineer.endWork)
  const skillLabels =
    engineer.skillLabels && engineer.skillLabels.length > 0
      ? engineer.skillLabels
      : engineer.skills.map((code) => SKILL_LABEL[code]).filter(Boolean)

  return (
    <AppPanel className="flex min-h-0 w-[346px] shrink-0 flex-col">
      <div className="relative flex shrink-0 flex-col gap-1 px-5 pt-5 pr-12">
        <h2 className="text-xl font-semibold leading-7 text-[#18181b]">
          Карточка Инженера
        </h2>
        <button
          type="button"
          aria-label="Закрыть"
          onClick={onClose}
          className="absolute top-4 right-4 flex size-8 cursor-pointer items-center justify-center text-[#71717a] transition-colors hover:bg-[#f5f5f5]"
          style={{ borderRadius: 8 }}
        >
          <RiCloseLine size={16} />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-4">
        <div className="flex flex-col items-center gap-3 pt-1">
          <span
            className="relative flex size-16 items-center justify-center bg-[#ebebec] text-lg font-semibold leading-7 text-[#18181b]"
            style={{ borderRadius: 999 }}
          >
            {getInitials(engineer.name)}
            {engineer.isLead ? (
              <span
                title="Бригадир"
                className="absolute -bottom-0.5 -left-0.5 flex size-5 items-center justify-center bg-white text-[#52525b] shadow-sm"
                style={{ borderRadius: 6 }}
              >
                <RiVipCrown2Fill size={12} />
              </span>
            ) : null}
          </span>
          <div className="flex flex-col items-center gap-0.5 text-center">
            <span className="text-base font-semibold leading-6 text-[#18181b]">
              {engineer.name}
            </span>
            {engineer.position ? (
              <span className="text-sm leading-6 text-[#71717a]">
                {engineer.position}
              </span>
            ) : null}
          </div>
        </div>

        <Field label="Доступный транспорт">
          <span className="flex flex-wrap gap-1.5">
            <Chip>
              <span className="inline-flex items-center gap-1">
                {TransportIcon ? (
                  <TransportIcon size={14} className="shrink-0 text-[#71717a]" />
                ) : null}
                {TRANSPORT_LABEL[engineer.transport] ?? engineer.transport}
              </span>
            </Chip>
          </span>
        </Field>

        {engineer.position ? (
          <Field label="Квалификация">
            <div className="flex flex-col gap-0.5">
              <span>{engineer.position}</span>
              {engineer.qualificationHint ? (
                <span className="text-xs leading-5 text-[#71717a]">
                  {engineer.qualificationHint}
                </span>
              ) : null}
            </div>
          </Field>
        ) : null}

        {skillLabels.length > 0 ? (
          <Field label="Навыки">
            <span className="flex flex-wrap gap-1.5">
              {skillLabels.map((label) => (
                <Chip key={label}>{label}</Chip>
              ))}
            </span>
          </Field>
        ) : null}

        {engineer.brigadeName ? (
          <Field label="Бригада">{engineer.brigadeName}</Field>
        ) : null}

        {workDay ? <Field label="Рабочий день">{workDay}</Field> : null}
      </div>

      {onEdit ? (
        <div className="shrink-0 px-5 pt-2 pb-5">
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex h-9 w-full cursor-pointer items-center justify-center bg-[#0485f7] text-sm font-medium leading-5 text-[#fcfcfc] transition-colors hover:bg-[#0374d9]"
            style={{ borderRadius: 8 }}
          >
            Редактировать
          </button>
        </div>
      ) : null}
    </AppPanel>
  )
}
