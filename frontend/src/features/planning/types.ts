export type RecalculateResult = {
  plan_id: number
  version: number
  assigned: number
  unassigned: number
}

export type PlanId = number
export type AssignmentId = number

export type PlanVersion = {
  plan_id: number
  version: number
  created_at: string
}

export type DayOverview = {
  plan_id: number | null
  plan_version: number | null
  has_plan: boolean
  tickets: {
    assigned: number | null
    total: number
  }
  engineers: {
    engaged: number | null
    total: number
  }
  planned_dates: string[]
  plans: PlanVersion[]
}

/** Насколько пересчёт может менять уже составленный план (Modal «Обновить план»). */
export type PlanRebuildLevel = 'fixed' | 'engineer' | 'free'
/** Как делить заявки между инженерами. */
export type PlanDistribution = 'even' | 'efficient'
