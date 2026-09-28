export type EngineerId = number
export type BrigadeId = number

export type SkillCode = 'connection' | 'local' | 'emergency'
export type TransportCode = 'car' | 'public' | 'bike' | 'walking'
export type QualificationCode = 'master' | 'worker' | 'novice'
/** Где обедают: у последней заявки, в офисе или в своей точке. */
export type LunchPlace = 'last_request' | 'office' | 'point'

/** Компактная карточка обзора дня. */
export type Engineer = {
  id: number
  name: string
  transport: string
  transport_label: string
  skill: string | null
  brigade_id?: number
  skills?: string[]
  is_lead?: boolean
}

export type PersonnelBrigade = {
  id: number
  name: string
  number: string
  regionId: number
  engineersCount: number
  leaderName?: string | null
  leaderShortName?: string | null
  officeAddress: string | null
  /** Точка офиса [lng, lat] — старт инженеров. */
  officePoint: [number, number] | null
  /** Рабочий день бригады, «HH:MM:SS». */
  startWork: string | null
  endWork: string | null
  /** ISO-номера рабочих дней: 1 — понедельник, 7 — воскресенье. */
  workDays: number[]
  areaIds: number[]
  /** Окно обеда, «HH:MM:SS»: час внутри него, когда именно — решает планировщик. */
  lunchStart: string | null
  lunchEnd: string | null
  lunchPlace: LunchPlace
  /** Место обеда «в своей точке»: адрес и точка [lng, lat]. */
  lunchAddress: string | null
  lunchPoint: [number, number] | null
}

export type AddressSuggestion = {
  address: string
  lat: number
  lon: number
  /** С номером дома — только такой адрес годится для офиса. */
  hasHouse: boolean
}

export type BrigadeArea = {
  id: number
  name: string
}

export type UpdateBrigadeBody = {
  office_address: string
  /** Точка, поставленная на карте; без неё адрес ищет геокодер. */
  office_lat?: number
  office_lon?: number
  area_ids: number[]
  work_days: number[]
  start_work: string
  end_work: string
  lunch_start: string
  lunch_end: string
  lunch_place: LunchPlace
  /** Только для «в своей точке». */
  lunch_address?: string
  lunch_lat?: number
  lunch_lon?: number
}

export type CreateBrigadeBody = {
  region_id: number
  name: string
  office_address: string
  office_lat: number
  office_lon: number
  work_days: number[]
  start_work: string
  end_work: string
}

export type UpdateBrigadeResult = PersonnelBrigade & {
  /** Скольким инженерам рабочий день переставлен вслед за бригадой. */
  rescheduledEngineers: number
  officeMoved: boolean
}

export type PersonnelEngineer = {
  id: number
  brigadeId: number
  brigadeName?: string | null
  name: string
  skills: SkillCode[]
  skillLabels?: string[]
  transport: TransportCode
  /** Бригадир — корона на аватаре и в карточке бригады. */
  isLead?: boolean
  qualification?: QualificationCode | null
  /** Подпись квалификации: Мастер / Бывалый / Новичок. */
  position?: string | null
  qualificationHint?: string | null
  startWork?: string | null
  endWork?: string | null
  /** Своя смена; без неё рабочий день идёт за бригадой. */
  ownSchedule?: boolean
  /** Рабочие дни (ISO): свои или бригады. */
  workDays: number[]
  /** Свой график; без него дни идут за бригадой. */
  ownWorkDays: boolean
  /** Окно обеда: своё или бригады. */
  lunchStart: string | null
  lunchEnd: string | null
  ownLunchTime: boolean
  /** Место обеда: своё или бригады. */
  lunchPlace: LunchPlace
  ownLunchPlace: boolean
  lunchAddress: string | null
  lunchPoint: [number, number] | null
  homeAddress: string | null
}

export type PersonnelFilterOptions = {
  skills: string[]
  transports: string[]
  qualifications: string[]
}

/** Поля формы инженера — одни и те же при добавлении и редактировании. */
export type EngineerBody = {
  name: string
  brigade_id: number
  transport: TransportCode
  skills: SkillCode[]
  qualification?: QualificationCode
  home_address?: string | null
  /** Без часов — рабочий день бригады, и дальше он меняется вместе с ней. */
  start_work?: string
  end_work?: string
  /** Без дней — рабочие дни бригады. */
  work_days?: number[]
  /** Без окна обеда — окно бригады, без места — место бригады. */
  lunch_start?: string
  lunch_end?: string
  lunch_place?: LunchPlace
  lunch_address?: string
  lunch_lat?: number
  lunch_lon?: number
}

export type CreateEngineerBody = EngineerBody & {
  is_lead?: boolean
}

export type EngineersListArgs = {
  regionId?: number | null
  brigadeId?: number | null
  q?: string
  skills?: string[]
  transports?: string[]
  qualifications?: string[]
}
