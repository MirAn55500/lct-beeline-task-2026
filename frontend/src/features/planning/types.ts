import type { RebuildLevel } from '@/shared/ui'

/** Уровень перестроения: Фикс / Инженерный / Свободный. */
export type RemakeLevel = RebuildLevel

/** Алиас для UI-диалога перестроения плана. */
export type PlanRebuildLevel = RemakeLevel

/** Распределение: Равномерное / Эффективное. */
export type PlanDistribution = 'even' | 'efficient'

export type ComparisonLine = {
  label: string
  baseline: string
  optimized: string
  verdict: string
}

export type PlanComparison = {
  summary: string
  lines: ComparisonLine[]
}

export type RecalculateResult = {
  plan_id: number
  version: number
  assigned: number
  unassigned: number
  comparison?: PlanComparison | null
}

export type PlanEventType = 'cancel_request' | 'engineer_unavailable'

export type PlanEventResult = {
  plan_id: number
  version: number
  assigned: number
  unassigned: number
  summary: string
  warnings: string[]
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
  /** План этого дня считается в фоне после загрузки заявок. */
  planning?: boolean
  /** Почему последний фоновый расчёт не удался. */
  planning_error?: string | null
  /** Примерно через сколько секунд фоновый расчёт закончится. */
  planning_eta_seconds?: number | null
  /** Примерно сколько секунд займёт «Обновить план». */
  rebuild_eta_seconds?: number | null
  travel_minutes?: number | null
  distance_km?: number | null
}
