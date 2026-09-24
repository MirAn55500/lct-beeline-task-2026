import {
  SKILL_LABEL,
  TRANSPORT_LABEL,
  type PersonnelEngineer,
} from '@/features/personnel/mocks'

import type { EngineersExportFormat } from '../ui/PersonnelHeader'

function toRows(engineers: PersonnelEngineer[]) {
  return engineers.map((item) => ({
    id: item.id,
    name: item.name,
    skills: item.skills.map((code) => SKILL_LABEL[code]),
    transport: TRANSPORT_LABEL[item.transport],
  }))
}

function csvCell(value: string | number) {
  const text = String(value)
  return /[",;\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function serialize(engineers: PersonnelEngineer[], format: EngineersExportFormat) {
  const rows = toRows(engineers)
  if (format === 'json') {
    return { body: JSON.stringify(rows, null, 2), type: 'application/json' }
  }
  const header = ['id', 'ФИО', 'Навыки', 'Транспорт']
  const lines = rows.map((row) =>
    [row.id, row.name, row.skills.join(', '), row.transport].map(csvCell).join(';'),
  )
  // BOM — чтобы Excel открыл кириллицу без кракозябр.
  return { body: `﻿${[header.join(';'), ...lines].join('\n')}`, type: 'text/csv' }
}

/** Выгрузка инженеров в файл прямо из браузера — без бэкенда. */
export function downloadEngineers(
  engineers: PersonnelEngineer[],
  format: EngineersExportFormat,
  fileName: string,
) {
  const { body, type } = serialize(engineers, format)
  const url = URL.createObjectURL(new Blob([body], { type: `${type};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${fileName}.${format}`
  link.click()
  URL.revokeObjectURL(url)
}
