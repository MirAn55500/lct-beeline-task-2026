import { toast } from '@heroui/react'

import { MOCK_MAP_REGIONS, PLANS } from '@/features/planning/mocks'
import { downloadTextFile } from '@/shared/lib'

import type { Ticket } from '../api'

export type TicketsExportFormat = 'csv' | 'json'

/** Колонки как в контрольной выгрузке «Восток». */
const HEADER = [
  'Заявка',
  'Тип заявки BK',
  'Статус BK',
  'Тип заявки HD',
  'Начало',
  'Окончание',
  'Район',
  'Адрес',
  'Бригада',
  'Подключение',
  'Гигабитное подключение',
] as const

type ExportRow = Record<(typeof HEADER)[number], string>

function pad2(value: number) {
  return String(value).padStart(2, '0')
}

/** `17.08.2026 20:00` — как в контрольном CSV. */
function formatMoment(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return (
    `${pad2(date.getDate())}.${pad2(date.getMonth() + 1)}.${date.getFullYear()} ` +
    `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
  )
}

function toRow(ticket: Ticket): ExportRow {
  return {
    Заявка: ticket.number,
    'Тип заявки BK': ticket.category,
    'Статус BK': ticket.status ?? '',
    'Тип заявки HD': ticket.hd ?? '',
    Начало: formatMoment(ticket.window_start),
    Окончание: formatMoment(ticket.window_end),
    Район: ticket.district ?? '',
    Адрес: ticket.address,
    // В контрольной выгрузке «Бригада» — назначенный исполнитель.
    Бригада: ticket.engineer ?? '',
    // В модели нет FMC/FTTB и гигабита — колонки оставляем пустыми для совместимости формата.
    Подключение: '',
    'Гигабитное подключение': '',
  }
}

/** Заявки мокового плана региона — для выгрузки, пока backend не отвечает. */
export function mockTickets(regionId: number, date: string): Ticket[] {
  const index = MOCK_MAP_REGIONS.findIndex((item) => item.id === regionId)
  const plan = PLANS[index]
  if (!plan || plan.date !== date) return []
  const engineerName = new Map(plan.engineers.map((item) => [item.id, item.name]))
  const assignee = new Map<string, string>()
  for (const route of plan.routes) {
    const name = engineerName.get(route.engineerId) ?? ''
    for (const visit of route.visits) assignee.set(visit.requestId, name)
  }
  return plan.requests.map((request, order) => {
    const engineer = assignee.get(request.id) ?? null
    return {
      id: order + 1,
      number: request.id,
      category: request.type,
      reason: null,
      engineer,
      assigned: engineer != null,
      window: '',
      window_start: request.window[0],
      window_end: request.window[1],
      address: request.address,
      status: engineer != null ? 'Назначена' : 'Не назначена',
      hd: '',
      district: '',
    }
  })
}

function csvCell(value: string) {
  return /[";\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

function serialize(tickets: Ticket[], format: TicketsExportFormat) {
  const rows = tickets.map(toRow)
  if (format === 'json') {
    return {
      body: JSON.stringify(rows, null, 2),
      type: 'application/json',
    }
  }
  const lines = [
    HEADER.join(';'),
    ...rows.map((row) => HEADER.map((key) => csvCell(row[key])).join(';')),
  ]
  return {
    body: `\uFEFF${lines.join('\n')}`,
    type: 'text/csv',
  }
}

export function downloadTickets(
  tickets: Ticket[],
  format: TicketsExportFormat,
  fileName: string,
) {
  if (tickets.length === 0) {
    toast.danger('Нет заявок для экспорта')
    return
  }
  const { body, type } = serialize(tickets, format)
  downloadTextFile(body, type, `${fileName}.${format}`)
  toast.success(format === 'csv' ? 'CSV скачан' : 'JSON скачан')
}
