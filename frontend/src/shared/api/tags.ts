/** Общие tagTypes для инвалидации кэша RTK Query. */
export const apiTagTypes = [
  'Ticket',
  'Engineer',
  'Brigade',
  'Plan',
  'Assignment',
  'Catalog',
] as const

export type ApiTagType = (typeof apiTagTypes)[number]
