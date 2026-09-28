import { downloadTextFile } from '@/shared/lib'

/**
 * Шаблон профилей инженеров — колонки, которые читает backend
 * (modules/personnel/importer.py). Разделитель «;», BOM для Excel.
 */
const COLUMNS = [
  'ФИО',
  'Бригада',
  'Квалификация',
  'Навыки',
  'Транспорт',
  'Начало смены',
  'Конец смены',
  'Домашний адрес',
]

const EXAMPLE_ROWS = [
  [
    'Артём Соколов',
    'Бригада Юго-восток',
    'Мастер',
    'Работы на подключение и дозаказы',
    'Пешеход',
    '09:00',
    '22:00',
    '',
  ],
  [
    'Мария Белова',
    'Бригада Юго-восток',
    'Бывалый',
    'Локальные работы',
    'Общ. транспорт',
    '09:00',
    '22:00',
    '',
  ],
  [
    'Игорь Кузнецов',
    'Бригада Юго-восток',
    'Новичок',
    'Работы на подключение и дозаказы, Локальные работы',
    'Автомобиль',
    '09:00',
    '22:00',
    '',
  ],
]

const TEMPLATE =
  '\ufeff' + [COLUMNS, ...EXAMPLE_ROWS].map((row) => row.join(';')).join('\r\n') + '\r\n'

export const ENGINEERS_TEMPLATE_NAME = 'Шаблон_инженеров.csv'

export const ENGINEERS_TEMPLATE_SIZE = formatFileSize(new Blob([TEMPLATE]).size)

export function downloadEngineersTemplate() {
  downloadTextFile(TEMPLATE, 'text/csv', ENGINEERS_TEMPLATE_NAME)
}

export function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
}

export function isEngineersFile(file: File) {
  const name = file.name.toLowerCase()
  return (
    name.endsWith('.csv') ||
    name.endsWith('.json') ||
    file.type === 'text/csv' ||
    file.type === 'application/json'
  )
}

export const ENGINEERS_FILE_TYPES = ['.csv', 'text/csv', '.json', 'application/json']
