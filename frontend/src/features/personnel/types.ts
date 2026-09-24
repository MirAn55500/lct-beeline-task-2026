export type EngineerId = number
export type BrigadeId = number

export type SkillCode = 'connection' | 'local' | 'emergency'
export type TransportCode = 'car' | 'public' | 'bike' | 'walking'
export type QualificationCode = 'master' | 'worker' | 'novice'

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
  /** Подпись квалификации: Мастер / Работник / Новичок. */
  position?: string | null
  qualificationHint?: string | null
  startWork?: string | null
  endWork?: string | null
}

export type PersonnelFilterOptions = {
  skills: string[]
  transports: string[]
  qualifications: string[]
}

export type CreateEngineerBody = {
  name: string
  brigade_id: number
  transport: TransportCode
  skills: SkillCode[]
  start_work: string
  end_work: string
  is_lead?: boolean
  qualification?: QualificationCode
}

export type EngineersListArgs = {
  regionId?: number | null
  brigadeId?: number | null
  q?: string
  skills?: string[]
  transports?: string[]
  qualifications?: string[]
}
