/** Общие tagTypes для инвалидации кэша RTK Query. */
export const apiTagTypes = [
  'Ticket',
  'Engineer',
  'Brigade',
  'Plan',
  /** Выгрузка дня для Ганта/карты — отдельно от day-overview, чтобы не зациклить опрос. */
  'PlanExport',
  'Assignment',
  'Catalog',
] as const

export type ApiTagType = (typeof apiTagTypes)[number]
