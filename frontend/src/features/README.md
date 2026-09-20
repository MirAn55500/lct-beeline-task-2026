/**
 * features — вертикальные срезы домена (как modules на бэке).
 *
 * В каждой фиче:
 *   api.ts         — injectEndpoints в baseApi
 *   types.ts       — типы фичи
 *   components/    — UI только этой фичи
 *   model/         — опционально: createSlice для UI-стейта (фильтры, selection)
 *   index.ts       — публичный API фичи для pages
 *
 * Фича НЕ импортирует pages. Между фичами — только через публичный index, без циклов.
 */
