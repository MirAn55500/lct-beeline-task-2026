/** Уровень перестроения плана — `remake_level` backend. */
export type RebuildLevel = 'fix' | 'engineer' | 'free'

export const REBUILD_LEVELS: { id: RebuildLevel; label: string; hint: string }[] = [
  { id: 'fix', label: 'Фикс', hint: 'Можно добавить новую заявку только в свободное окно' },
  { id: 'engineer', label: 'Инженерный', hint: 'Заявки можно менять только в рамках одного инженера' },
  { id: 'free', label: 'Свободный', hint: 'Обратите внимание! На этом уровне перестраивается весь план' },
]
