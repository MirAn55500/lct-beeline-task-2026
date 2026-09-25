import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

import type {
  DayOverview,
  PlanDistribution,
  RecalculateResult,
  RemakeLevel,
} from './types'

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
      // Фоновый расчёт после загрузки закончился — обновить план, карту, Гант и заявки
      async onQueryStarted(_args, { dispatch, getCacheEntry, queryFulfilled }) {
        const wasPlanning = getCacheEntry().data?.planning ?? false
        try {
          const { data } = await queryFulfilled
          if (wasPlanning && !data.planning) dispatch(planningApi.util.invalidateTags(['Plan', 'Ticket']))
        } catch {
          // ошибку запроса покажет сам компонент
        }
      },
    }),
    recalculatePlan: build.mutation<
      RecalculateResult,
      {
        regionId: number
        date: string
        remakeLevel?: RemakeLevel
        /** @deprecated используйте remakeLevel */
        level?: RemakeLevel
        distribution?: PlanDistribution
      }
    >({
      query: ({ regionId, date, remakeLevel, level, distribution }) => ({
        url: '/api/planning/recalculate',
        method: 'POST',
        params: {
          region_id: regionId,
          date,
          ...((remakeLevel ?? level) != null
            ? { remake_level: remakeLevel ?? level }
            : {}),
          ...(distribution != null ? { distribution } : {}),
        },
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
