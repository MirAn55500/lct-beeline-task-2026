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
  const { body, type } = serialize(tickets, format)
  const url = URL.createObjectURL(new Blob([body], { type: `${type};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${fileName}.${format}`
  link.click()
  URL.revokeObjectURL(url)
}
