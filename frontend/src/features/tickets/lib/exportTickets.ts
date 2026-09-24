import type { Ticket } from '../api'

const COLUMNS: { title: string; value: (ticket: Ticket) => string }[] = [
  { title: 'Заявка', value: (ticket) => ticket.number },
  { title: 'Тип', value: (ticket) => ticket.category },
  { title: 'Адрес', value: (ticket) => ticket.address },
  { title: 'Окно', value: (ticket) => ticket.window },
  { title: 'Инженер', value: (ticket) => ticket.engineer ?? '' },
  { title: 'Причина неназначения', value: (ticket) => ticket.reason ?? '' },
]

function csvCell(value: string) {
  return /[;"\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/** Заявки дня в csv (через «;», как выгрузки БК) или json. */
export function downloadTickets(tickets: Ticket[], format: 'csv' | 'json', fileName: string) {
  const body =
    format === 'json'
      ? JSON.stringify(tickets, null, 2)
      : '﻿' +
        [COLUMNS.map((column) => column.title), ...tickets.map((ticket) => COLUMNS.map((column) => column.value(ticket)))]
          .map((row) => row.map(csvCell).join(';'))
          .join('\r\n')
  const type = format === 'json' ? 'application/json' : 'text/csv;charset=utf-8'
  const url = URL.createObjectURL(new Blob([body], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${fileName}.${format}`
  link.click()
  URL.revokeObjectURL(url)
}
