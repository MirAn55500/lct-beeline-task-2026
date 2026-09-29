import type { Time } from '@internationalized/date'

import type { LunchPlace } from '@/features/personnel/types'

import type { AddressPoint } from '../ui/AddressPointField'

/** Обед в формах бригады и инженера: варианты места и проверки окна, как у backend. */

/** Сколько длится обед: окно не может быть короче. */
export const LUNCH_MINUTES = 60

export const LUNCH_PLACES: { id: LunchPlace; label: string }[] = [
  { id: 'last_request', label: 'У последней заявки' },
  { id: 'office', label: 'В офисе' },
  { id: 'point', label: 'Своё место' },
]

/** Подпись под местом обеда: что это значит для маршрута. */
export function lunchPlaceNote(place: LunchPlace): string | null {
  if (place === 'last_request') return 'Там, где закончил работу, — без лишней дороги'
  if (place === 'office') return 'Дорогу в офис и обратно план учтёт'
  return null
}

export type LunchDraft = {
  timeFrom: Time | null
  timeTo: Time | null
  place: LunchPlace
  /** Место обеда для «своего места»: адрес и точка. */
  spot: AddressPoint
}

function minutes(value: Time) {
  return value.hour * 60 + value.minute
}

/** Что не так с окном обеда; null — всё в порядке. Правила те же, что у backend. */
export function lunchTimeError(
  lunch: LunchDraft,
  workFrom: Time | null,
  workTo: Time | null,
): string | null {
  if (lunch.timeFrom == null || lunch.timeTo == null) return 'Укажите начало и конец окна обеда'
  if (minutes(lunch.timeTo) - minutes(lunch.timeFrom) < LUNCH_MINUTES) {
    return 'Окно обеда должно быть не меньше часа'
  }
  if (workFrom != null && workTo != null) {
    const inside =
      Math.min(minutes(lunch.timeTo), minutes(workTo)) -
      Math.max(minutes(lunch.timeFrom), minutes(workFrom))
    if (inside < LUNCH_MINUTES) return 'Час обеда должен помещаться в рабочий день'
  }
  return null
}

/** Своё место выбрано, но точки ещё нет. */
export function lunchSpotMissing(lunch: LunchDraft): boolean {
  return (
    lunch.place === 'point' &&
    (lunch.spot.point == null || lunch.spot.address.trim() === '' || !lunch.spot.confirmed)
  )
}
