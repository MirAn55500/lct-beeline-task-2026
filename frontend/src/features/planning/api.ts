import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

import type { DayOverview, RecalculateResult } from './types'

export const planningApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getPlanningHealth: build.query<ModuleHealth, void>({
      query: () => '/api/planning/health',
    }),
    getDayOverview: build.query<
      DayOverview,
      { regionId: number; date: string; planId?: number | null }
    >({
      query: ({ regionId, date, planId }) => ({
        url: '/api/planning/day-overview',
        params: {
          region_id: regionId,
          date,
          ...(planId != null ? { plan_id: planId } : {}),
        },
      }),
      providesTags: ['Plan'],
    }),
    recalculatePlan: build.mutation<
      RecalculateResult,
      { regionId: number; date: string }
    >({
      query: ({ regionId, date }) => ({
        url: '/api/planning/recalculate',
        method: 'POST',
        params: { region_id: regionId, date },
      }),
      invalidatesTags: ['Plan', 'Ticket'],
    }),
  }),
})

export const {
  useGetDayOverviewQuery,
  useGetPlanningHealthQuery,
  useRecalculatePlanMutation,
} = planningApi
