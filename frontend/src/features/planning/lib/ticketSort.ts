/** Сортировка неназначенных заявок — одна и та же на карте и в Ганте. */
export type TicketSortKey = 'window' | 'number' | 'type'

export const TICKET_SORT_LABEL: Record<TicketSortKey, string> = {
  window: 'По времени визита',
  number: 'По номеру',
  type: 'По типу',
}

type Sortable = { id: string; typeLabel: string }

export function sortTickets<T extends Sortable>(
  tickets: T[],
  key: TicketSortKey,
  windowStart: (ticket: T) => number,
) {
  const copy = [...tickets]
  if (key === 'window') copy.sort((a, b) => windowStart(a) - windowStart(b))
  if (key === 'number') copy.sort((a, b) => a.id.localeCompare(b.id))
  if (key === 'type') copy.sort((a, b) => a.typeLabel.localeCompare(b.typeLabel, 'ru'))
  return copy
}
