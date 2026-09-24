/**
 * Шаблон выгрузки заявок: колонки, которые читает backend (modules/tickets/importer.py).
 * Разделитель — «;», как в выгрузках БК; BOM нужен, чтобы Excel открыл кириллицу.
 */
const COLUMNS = ['Заявка', 'Адрес', 'Район', 'Начало', 'Окончание', 'Тип заявки BK', 'Тип заявки HD', 'Статус BK']

const EXAMPLE_ROWS = [
  ['74198', 'Москва, Волгоградский пр-т, 128, корп. 5', 'Кузьминки', '10.10.2026 10:00', '10.10.2026 12:00', 'Подключение', 'Заявка на подключение', 'Не отправлена'],
  ['24980', 'Москва, Семёновская наб., 3/1, корп. 2', 'Соколиная Гора', '10.10.2026 12:00', '10.10.2026 14:00', 'Глобальная проблема', 'Авария', 'Не отправлена'],
  ['48227', 'Москва, ул. Саратовская, 16', 'Текстильщики', '10.10.2026 18:00', '10.10.2026 20:00', 'Локальная заявка', 'Нет линка', 'Не отправлена'],
]

const TEMPLATE = '﻿' + [COLUMNS, ...EXAMPLE_ROWS].map((row) => row.join(';')).join('\r\n') + '\r\n'

export const TICKETS_TEMPLATE_NAME = 'Шаблон_заявок.csv'

/** «2 КБ» — размер шаблона для подписи кнопки. */
export const TICKETS_TEMPLATE_SIZE = formatFileSize(new Blob([TEMPLATE]).size)

export function downloadTicketsTemplate() {
  const url = URL.createObjectURL(new Blob([TEMPLATE], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = TICKETS_TEMPLATE_NAME
  link.click()
  URL.revokeObjectURL(url)
}

/** 250880 → «245 КБ», как в карточке файла из макета. */
export function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
}

/** Выгрузку принимаем в csv или json — оба формата разбирает backend. */
export function isTicketsFile(file: File) {
  const name = file.name.toLowerCase()
  return name.endsWith('.csv') || name.endsWith('.json') || file.type === 'text/csv' || file.type === 'application/json'
}

export const TICKETS_FILE_TYPES = ['.csv', 'text/csv', '.json', 'application/json']
