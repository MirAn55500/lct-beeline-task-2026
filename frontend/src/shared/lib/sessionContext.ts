/** Регион и дата рабочей сессии вкладки — переживают переходы по разделам. */

const REGION_KEY = 'lct.session.regionId'
const DATE_KEY = 'lct.session.date'

function canUseStorage() {
  return typeof sessionStorage !== 'undefined'
}

export function readSessionRegionId(): number | null {
  if (!canUseStorage()) return null
  const raw = sessionStorage.getItem(REGION_KEY)
  if (!raw) return null
  const id = Number(raw)
  return Number.isInteger(id) && id > 0 ? id : null
}

export function writeSessionRegionId(regionId: number) {
  if (!canUseStorage() || !Number.isInteger(regionId) || regionId <= 0) return
  sessionStorage.setItem(REGION_KEY, String(regionId))
}

export function readSessionDate(): string | null {
  if (!canUseStorage()) return null
  const raw = sessionStorage.getItem(DATE_KEY)
  if (!raw || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null
  return raw
}

export function writeSessionDate(isoDate: string) {
  if (!canUseStorage() || !/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) return
  sessionStorage.setItem(DATE_KEY, isoDate)
}

/**
 * Query для ссылок меню: сначала то, что уже в адресе, иначе значение из сессии.
 * Так регион и день не сбрасываются при переходе Обзор ↔ План ↔ Персонал.
 */
export function preservedContextSearch(params: URLSearchParams): string {
  const next = new URLSearchParams()
  const region = params.get('region') ?? (readSessionRegionId()?.toString() ?? null)
  const date = params.get('date') ?? readSessionDate()
  if (region) next.set('region', region)
  if (date) next.set('date', date)
  const query = next.toString()
  return query ? `?${query}` : ''
}
