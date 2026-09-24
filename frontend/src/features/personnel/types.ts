export type EngineerId = number
export type BrigadeId = number

export type SkillCode = 'connection' | 'local' | 'emergency'
export type TransportCode = 'car' | 'public' | 'bike' | 'walking'

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
  name: string
  skills: SkillCode[]
  transport: TransportCode
  /** Бригадир — корона на аватаре и в карточке бригады. */
  isLead?: boolean
}

export type PersonnelFilterOptions = {
  skills: string[]
  transports: string[]
}

export type CreateEngineerBody = {
  name: string
  brigade_id: number
  transport: TransportCode
  skills: SkillCode[]
  start_work: string
  end_work: string
  is_lead?: boolean
}

export type EngineersListArgs = {
  regionId?: number | null
  brigadeId?: number | null
  q?: string
  skills?: string[]
  transports?: string[]
}
