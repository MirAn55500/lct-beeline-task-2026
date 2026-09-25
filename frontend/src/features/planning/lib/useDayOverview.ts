import { skipToken } from '@reduxjs/toolkit/query/react'

import { planningApi, useGetDayOverviewQuery } from '../api'

type DayOverviewArgs = Parameters<typeof useGetDayOverviewQuery>[0]

/** Как часто переспрашивать сводку, пока план считается в фоне. */
const PLANNING_POLL_MS = 3000

/**
 * Сводка дня. Пока план считается в фоне после загрузки заявок (`planning`), она
 * переспрашивается раз в 3 с; когда расчёт закончится, `getDayOverview` сам обновит
 * план, карту, Гант и заявки.
 */
export function useDayOverview(args: DayOverviewArgs, options?: { skip?: boolean }) {
  const key = options?.skip ? skipToken : args
  const { data } = planningApi.endpoints.getDayOverview.useQueryState(key)
  return useGetDayOverviewQuery(key, { pollingInterval: data?.planning ? PLANNING_POLL_MS : 0 })
}
