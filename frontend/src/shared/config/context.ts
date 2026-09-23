export const REGIONS = ['Восток', 'Юго-восток', 'Юго-центр'] as const

export type Region = (typeof REGIONS)[number]

export const DEFAULT_REGION: Region = 'Восток'
