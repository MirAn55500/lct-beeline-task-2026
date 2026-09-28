import { toast } from '@heroui/react'

import { downloadTextFile } from '@/shared/lib'

import {
  QUALIFICATION_LABEL,
  SKILL_LABEL,
  TRANSPORT_LABEL,
  type PersonnelEngineer,
} from '@/features/personnel/mocks'
import type { QualificationCode } from '@/features/personnel/types'

import type { EngineersExportFormat } from '../ui/PersonnelHeader'

type ExportRow = {
  id: number
  name: string
  brigade: string
  qualification: string
  skills: string[]
  transport: string
  start_work: string
  end_work: string
}

function qualificationLabel(code: QualificationCode | null | undefined) {
  if (!code) return ''
  return QUALIFICATION_LABEL[code] ?? code
}

function toRows(engineers: PersonnelEngineer[]): ExportRow[] {
  return engineers.map((item) => ({
    id: item.id,
    name: item.name,
    brigade: item.brigadeName ?? '',
    qualification: item.position ?? qualificationLabel(item.qualification),
    skills:
      item.skillLabels && item.skillLabels.length > 0
        ? item.skillLabels
        : item.skills.map((code) => SKILL_LABEL[code]),
    transport: TRANSPORT_LABEL[item.transport] ?? item.transport,
    start_work: item.startWork?.slice(0, 5) ?? '',
    end_work: item.endWork?.slice(0, 5) ?? '',
  }))
}

function csvCell(value: string | number) {
  const text = String(value)
  return /[";\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function serialize(engineers: PersonnelEngineer[], format: EngineersExportFormat) {
  const rows = toRows(engineers)
  if (format === 'json') {
    return { body: JSON.stringify(rows, null, 2), type: 'application/json' }
  }
  const header = [
    'id',
    'ФИО',
    'Бригада',
    'Квалификация',
    'Навыки',
    'Транспорт',
    'Начало смены',
    'Конец смены',
  ]
  const lines = rows.map((row) =>
    [
      row.id,
      row.name,
      row.brigade,
      row.qualification,
      row.skills.join(', '),
      row.transport,
      row.start_work,
      row.end_work,
    ]
      .map(csvCell)
      .join(';'),
  )
  // BOM — чтобы Excel открыл кириллицу без кракозябр.
  return {
    body: `\uFEFF${[header.join(';'), ...lines].join('\n')}`,
    type: 'text/csv',
  }
}

/** Выгрузка инженеров в файл прямо из браузера — без бэкенда. */
export function downloadEngineers(
  engineers: PersonnelEngineer[],
  format: EngineersExportFormat,
  fileName: string,
) {
  if (engineers.length === 0) {
    toast.danger('Нет инженеров для экспорта')
    return
  }
  const { body, type } = serialize(engineers, format)
  downloadTextFile(body, type, `${fileName}.${format}`)
  toast.success(format === 'csv' ? 'CSV скачан' : 'JSON скачан')
}
