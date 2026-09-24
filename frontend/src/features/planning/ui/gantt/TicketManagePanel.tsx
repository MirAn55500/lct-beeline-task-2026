import { useState, type ReactNode } from 'react'
import { Dropdown, Tooltip } from '@heroui/react'
import { RiArrowDownSLine, RiInformationLine, RiRouterFill, RiTimeLine, RiTvLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { AppPanel, AppTooltipContent } from '@/shared/ui'

import type { GanttUnassigned } from '../../ganttTypes'
import { formatClock } from '../../lib/ganttPlacement'
import type { GanttTicketPatch } from '../../lib/usePlanGanttBoard'
import type { GanttTicketType } from '../../mocks/gantt'

type TicketManagePanelProps = {
  ticket: GanttUnassigned
  ticketTypes: GanttTicketType[]
  qualifications: Record<string, string[]>
  onSave: (patch: GanttTicketPatch) => void
  onClose: () => void
}

/** 545 → «09:05» для input[type=time]. */
const toInput = (value: number) => formatClock(value).padStart(5, '0')

function fromInput(value: string) {
  const [hours, minutes] = value.split(':').map(Number)
  if (hours == null || minutes == null || Number.isNaN(hours) || Number.isNaN(minutes)) return null
  return hours * 60 + minutes
}

function FieldLabel({ children, required, hint }: { children: ReactNode; required?: boolean; hint?: string }) {
  return (
    <div className="flex items-center gap-1 text-sm leading-6 font-medium text-[#18181b]">
      {children}
      {required ? <span className="text-[#ff383c]">*</span> : null}
      {hint ? (
        <Tooltip delay={200}>
          <Tooltip.Trigger className="inline-flex cursor-help text-[#71717a] outline-none">
            <RiInformationLine size={12} />
          </Tooltip.Trigger>
          <AppTooltipContent className="max-w-[280px] text-left">{hint}</AppTooltipContent>
        </Tooltip>
      ) : null}
    </div>
  )
}

const INPUT =
  'flex h-9 w-full items-center border border-[#dedee0] bg-white px-3 text-sm leading-5 text-[#18181b] outline-none focus-within:border-[#0485f7]'

/**
 * «Управление заявкой» — правка снятой заявки перед повторной постановкой.
 * Главное здесь — новое время, согласованное с клиентом.
 */
export function TicketManagePanel({ ticket, ticketTypes, qualifications, onSave, onClose }: TicketManagePanelProps) {
  const windowLength = ticket.windowTo - ticket.windowFrom
  const [typeLabel, setTypeLabel] = useState(ticket.typeLabel)
  const [needsBox, setNeedsBox] = useState(ticket.needsBox)
  const [needsRouter, setNeedsRouter] = useState(ticket.needsRouter)
  const [address, setAddress] = useState(ticket.address)
  const [start, setStart] = useState(ticket.windowFrom)

  const type = ticketTypes.find((item) => item.label === typeLabel)
  const skill = type?.skill ?? ticket.skill
  const levels = qualifications[skill] ?? []
  // Прежнее время уже не выполнить — пока его не сменили, поле в ошибке.
  const timeError = ticket.needsApproval === true && start === ticket.windowFrom
  const canSave = !timeError && address.trim() !== ''

  return (
    <AppPanel className="flex w-[346px] shrink-0 flex-col overflow-hidden">
      <div className="flex flex-col gap-1 px-5 pt-5 pb-2">
        <h2 className="text-xl leading-7 font-semibold text-[#18181b]">Управление заявкой</h2>
        <p className="text-sm leading-6 text-[#71717a]">
          Заявка №{ticket.id} · {ticket.address}
        </p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-3">
        <div className="flex flex-col gap-1">
          <FieldLabel required>Тип заявки</FieldLabel>
          <Dropdown>
            <Dropdown.Trigger
              className={cn(INPUT, 'cursor-pointer justify-between pr-3 transition-colors hover:bg-[#fafafa]')}
              style={{ borderRadius: 8 }}
            >
              {typeLabel}
              <RiArrowDownSLine size={16} className="shrink-0" />
            </Dropdown.Trigger>
            <Dropdown.Popover
              placement="bottom start"
              offset={4}
              className="w-[306px] border-0 bg-white p-1 outline-none"
              style={{ borderRadius: 12, boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)' }}
            >
              <Dropdown.Menu
                aria-label="Тип заявки"
                selectionMode="single"
                selectedKeys={new Set([typeLabel])}
                onAction={(key) => setTypeLabel(String(key))}
                className="flex flex-col outline-none"
              >
                {ticketTypes.map((item) => (
                  <Dropdown.Item
                    key={item.label}
                    id={item.label}
                    textValue={item.label}
                    className="flex h-9 cursor-pointer items-center px-3 text-sm leading-5 font-medium text-[#18181b] outline-none data-[focused]:bg-[#f5f5f5] data-[selected]:bg-[#f5f5f5]"
                    style={{ borderRadius: 8 }}
                  >
                    {item.label}
                  </Dropdown.Item>
                ))}
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
          <p className="text-sm leading-5 text-[#71717a]">
            Допустимая квалификация: {levels.length > 0 ? levels.join(', ') : 'нет инженеров с навыком'}
          </p>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel>Требуемое оборудование</FieldLabel>
          <div className="flex gap-1 pt-1">
            {[
              { label: 'Приставка', icon: RiTvLine, active: needsBox, toggle: () => setNeedsBox((value) => !value) },
              { label: 'Роутер', icon: RiRouterFill, active: needsRouter, toggle: () => setNeedsRouter((value) => !value) },
            ].map(({ label, icon: ChipIcon, active, toggle }) => (
              <button
                key={label}
                type="button"
                aria-pressed={active}
                onClick={toggle}
                className={cn(
                  'flex h-7 cursor-pointer items-center gap-1 px-3 text-sm leading-6 font-medium transition-colors',
                  active ? 'bg-[#0485f7] text-[#fcfcfc] hover:bg-[#0374d9]' : 'bg-[#ebebec] text-[#18181b] hover:bg-[#e0e0e2]',
                )}
                style={{ borderRadius: 8 }}
              >
                <ChipIcon size={14} />
                {label}
              </button>
            ))}
          </div>
        </div>

        <span aria-hidden className="h-px shrink-0 bg-[#e4e4e7]" />

        <label className="flex flex-col gap-1">
          <FieldLabel required>Адрес точки</FieldLabel>
          <input
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            className={INPUT}
            style={{ borderRadius: 8 }}
          />
        </label>

        <div className="flex flex-col gap-1">
          <FieldLabel required hint="Окно прибытия: инженер должен начать работу внутри него">
            Время выполнения
          </FieldLabel>
          <div className="flex items-center">
            <label
              className={cn(INPUT, 'gap-2', timeError && 'border-[#ff383c] focus-within:border-[#ff383c]')}
              style={{ borderRadius: 8 }}
            >
              <input
                type="time"
                step={600}
                aria-label="Начало окна"
                aria-invalid={timeError}
                value={toInput(start)}
                onChange={(event) => {
                  const next = fromInput(event.target.value)
                  if (next != null) setStart(next)
                }}
                className="min-w-0 flex-1 bg-transparent outline-none [&::-webkit-calendar-picker-indicator]:hidden"
              />
              <RiTimeLine size={16} className="shrink-0" />
            </label>
            <span className="w-3 shrink-0 text-center text-sm leading-5 text-[#71717a]">-</span>
            <span
              className="flex h-9 w-full items-center justify-between bg-[#ebebec] px-3 text-sm leading-5 text-[#71717a]"
              style={{ borderRadius: 8 }}
              aria-label="Конец окна"
            >
              {toInput(start + windowLength)}
              <RiTimeLine size={16} className="shrink-0" />
            </span>
          </div>
          <p className="text-sm leading-5 text-[#71717a]">
            Измените и согласуйте новое время заявки с клиентом, или найдите свободного инженера
          </p>
        </div>
      </div>

      <div className="flex shrink-0 gap-2 px-5 pt-2 pb-5">
        <button
          type="button"
          onClick={onClose}
          className="h-9 flex-1 cursor-pointer border border-[#dedee0] bg-white px-4 text-sm leading-5 font-medium text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
          style={{ borderRadius: 8 }}
        >
          Отменить
        </button>
        <button
          type="button"
          disabled={!canSave}
          onClick={() =>
            onSave({
              typeLabel,
              skill,
              duration: type?.duration ?? ticket.duration,
              needsBox,
              needsRouter,
              address: address.trim(),
              windowFrom: start,
              windowTo: start + windowLength,
            })
          }
          className={cn(
            'h-9 flex-1 bg-[#0485f7] px-4 text-sm leading-5 font-medium text-[#fcfcfc] transition-colors',
            canSave ? 'cursor-pointer hover:bg-[#0374d9]' : 'cursor-not-allowed opacity-50',
          )}
          style={{ borderRadius: 8 }}
        >
          Сохранить
        </button>
      </div>
    </AppPanel>
  )
}
