/**
 * Константы и подписи UI страницы «Персонал».
 * Данные бригад/инженеров приходят с API — см. api.ts.
 */

import type {
  PersonnelEngineer,
  SkillCode,
  TransportCode,
} from './types'

export type {
  PersonnelBrigade,
  PersonnelEngineer,
  SkillCode,
  TransportCode,
} from './types'

export const SKILL_LABEL: Record<SkillCode, string> = {
  connection: 'Работы на подключение и дозаказы',
  local: 'Локальные работы',
  emergency: 'Аварийные работы',
}

export const TRANSPORT_LABEL: Record<TransportCode, string> = {
  car: 'Автомобиль',
  public: 'Общ. транспорт',
  bike: 'Велосипед',
  walking: 'Пешеход',
}

export const QUALIFICATION_LABEL = {
  master: 'Мастер',
  worker: 'Бывалый',
  novice: 'Новичок',
} as const

export const QUALIFICATION_OPTIONS = Object.values(QUALIFICATION_LABEL)

/** «Саша Белый» → «Белый С.» — как подпись бригадира в макете. */
export function shortName(name: string): string {
  const [first, last] = name.split(/\s+/)
  return last ? `${last} ${first![0]}.` : name
}

/** Следующий свободный id — только для локальных демо-батчей загрузки файлом. */
export function nextEngineerId(engineers: PersonnelEngineer[]): number {
  return engineers.reduce((max, item) => Math.max(max, item.id), 0) + 1
}

const ALL: SkillCode[] = ['connection', 'local', 'emergency']

const UPLOAD_POOL: [name: string, skills: SkillCode[], transport: TransportCode][] = [
  ['Григорий Панов', ['local'], 'car'],
  ['Ксения Титова', ['connection'], 'public'],
  ['Роман Беляев', ALL, 'bike'],
  ['Светлана Егорова', ['emergency'], 'walking'],
  ['Максим Гусев', ['connection', 'local'], 'car'],
]

/**
 * Пачка «загруженных из файла» инженеров.
 * Пока бэкенд не принимает файл профилей — демо для UI; затем уходит в createEngineer.
 */
export function createUploadBatch(
  brigadeId: number,
  engineers: PersonnelEngineer[],
  count = 3,
): PersonnelEngineer[] {
  const startId = nextEngineerId(engineers)
  return UPLOAD_POOL.slice(0, count).map(([name, skills, transport], index) => ({
    id: startId + index,
    brigadeId,
    name,
    skills,
    transport,
  }))
}
