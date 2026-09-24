/**
 * Моки страницы «Персонал» по макету Figma — пока нет API бригад.
 * Заменить на RTK Query, когда появятся эндпоинты.
 */

export type SkillCode = 'connection' | 'local' | 'emergency'
export type TransportCode = 'car' | 'public' | 'bike' | 'walking'
export type QualificationCode = 'master' | 'worker' | 'novice'

export type PersonnelBrigade = {
  id: number
  name: string
  number: string
}

export type PersonnelEngineer = {
  id: number
  brigadeId: number
  name: string
  /** Квалификация инженера — подпись под именем, см. QUALIFICATION_LABEL. */
  position: string
  skills: SkillCode[]
  transport: TransportCode
  /** Бригадир — корона на аватаре и в карточке бригады. */
  isLead?: boolean
}

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

// Порядок совпадает с фильтром «Квалификация» в макете Figma.
export const QUALIFICATION_ORDER: QualificationCode[] = ['master', 'worker', 'novice']

export const QUALIFICATION_LABEL: Record<QualificationCode, string> = {
  master: 'Мастер',
  worker: 'Работяга',
  novice: 'Новичек',
}

export const QUALIFICATION_HINT: Record<QualificationCode, string> = {
  master: 'Выполняет задачи быстрее нормативов',
  worker: 'Справляется с задачами по нормативу',
  novice: 'Работает под присмотром наставника',
}

export const MOCK_BRIGADES: PersonnelBrigade[] = [
  { id: 1, name: 'Восток', number: '01' },
  { id: 2, name: 'Юго-восток', number: '01' },
  { id: 3, name: 'Юго-центр', number: '01' },
]

const ALL: SkillCode[] = ['connection', 'local', 'emergency']

// Первые девять строк повторяют макет, остальные — для других бригад.
const ROWS: [
  name: string,
  skills: SkillCode[],
  transport: TransportCode,
  qualification: QualificationCode,
][] = [
  ['Саша Белый', ALL, 'car', 'master'],
  ['Павел Козлов', ['local'], 'public', 'worker'],
  ['Ирина Смирнова', ['connection', 'local'], 'bike', 'novice'],
  ['Олег Петров', ALL, 'public', 'master'],
  ['Анна Волкова', ['connection'], 'walking', 'worker'],
  ['Дмитрий Орлов', ['connection', 'emergency'], 'car', 'novice'],
  ['Мария Кузнецова', ALL, 'bike', 'master'],
  ['Илья Соколов', ['emergency'], 'public', 'worker'],
  ['Никита Лебедев', ['local', 'emergency'], 'car', 'novice'],
  ['Вера Морозова', ['connection'], 'public', 'worker'],
  ['Артём Новиков', ALL, 'car', 'master'],
  ['Юлия Попова', ['local'], 'walking', 'novice'],
]

const SIZE_BY_BRIGADE: Record<number, number> = { 1: 9, 2: 11, 3: 12 }

export const MOCK_ENGINEERS: PersonnelEngineer[] = MOCK_BRIGADES.flatMap((brigade) =>
  ROWS.slice(0, SIZE_BY_BRIGADE[brigade.id]).map(
    ([name, skills, transport, qualification], index) => ({
      id: brigade.id * 100 + index,
      brigadeId: brigade.id,
      name,
      position: QUALIFICATION_LABEL[qualification],
      skills,
      transport,
      isLead: index === brigade.id - 1,
    }),
  ),
)

/** «Саша Белый» → «Белый С.» — как подпись бригадира в макете. */
export function shortName(name: string): string {
  const [first, last] = name.split(/\s+/)
  return last ? `${last} ${first![0]}.` : name
}

/** Следующий свободный id — для инженеров, добавленных в форме на моках. */
export function nextEngineerId(engineers: PersonnelEngineer[]): number {
  return engineers.reduce((max, item) => Math.max(max, item.id), 0) + 1
}

// Пул для демо загрузки файлом — «Добавить инженера» → «Файлом».
const UPLOAD_POOL: [
  name: string,
  skills: SkillCode[],
  transport: TransportCode,
  qualification: QualificationCode,
][] = [
  ['Григорий Панов', ['local'], 'car', 'worker'],
  ['Ксения Титова', ['connection'], 'public', 'novice'],
  ['Роман Беляев', ALL, 'bike', 'master'],
  ['Светлана Егорова', ['emergency'], 'walking', 'worker'],
  ['Максим Гусев', ['connection', 'local'], 'car', 'novice'],
]

/** Пачка «загруженных из файла» инженеров для демонстрации макета. */
export function createUploadBatch(
  brigadeId: number,
  engineers: PersonnelEngineer[],
  count = 3,
): PersonnelEngineer[] {
  const startId = nextEngineerId(engineers)
  return UPLOAD_POOL.slice(0, count).map(([name, skills, transport, qualification], index) => ({
    id: startId + index,
    brigadeId,
    name,
    position: QUALIFICATION_LABEL[qualification],
    skills,
    transport,
  }))
}
