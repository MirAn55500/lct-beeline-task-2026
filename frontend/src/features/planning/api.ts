import { toast } from '@heroui/react'

import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

import type {
  DayOverview,
  PlanDistribution,
  PlanEventResult,
  PlanEventType,
  RecalculateResult,
  RemakeLevel,
} from './types'

/**
 * Дни, план которых сейчас считается в фоне, — `регион:день`. Сводку дня запрашивают
 * несколько экранов с разными параметрами, а об окончании расчёта нужно сказать один раз.
 */
const planningDays = new Set<string>()

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
      async onQueryStarted(args, { dispatch, getCacheEntry, queryFulfilled }) {
        const day = `${args.regionId}:${args.date}`
        if (getCacheEntry().data?.planning) planningDays.add(day)
        try {
          const { data } = await queryFulfilled
          if (data.planning) {
            planningDays.add(day)
            return
          }
          if (!planningDays.delete(day)) return
          dispatch(planningApi.util.invalidateTags(['Plan', 'Ticket']))
          if (data.planning_error) {
            toast.danger('План работ не составлен', { description: data.planning_error })
            return
          }
          const latest = Math.max(0, ...data.plans.map((plan) => plan.version))
          toast.success(latest ? `План №${latest} составлен` : 'План работ составлен', {
            description:
              data.plan_version === latest && data.tickets.assigned != null
                ? `Назначено ${data.tickets.assigned} из ${data.tickets.total}`
                : undefined,
          })
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
        compare?: boolean
      }
    >({
      query: ({ regionId, date, remakeLevel, level, distribution, compare }) => ({
        url: '/api/planning/recalculate',
        method: 'POST',
        params: {
          region_id: regionId,
          date,
          ...((remakeLevel ?? level) != null
            ? { remake_level: remakeLevel ?? level }
            : {}),
          ...(distribution != null ? { distribution } : {}),
          ...(compare ? { compare: true } : {}),
        },
      }),
      invalidatesTags: ['Plan', 'Ticket'],
    }),
    applyPlanEvent: build.mutation<
      PlanEventResult,
      {
        regionId: number
        date: string
        type: PlanEventType
        requestId?: number
        engineerId?: number
        at?: string
      }
    >({
      query: ({ regionId, date, type, requestId, engineerId, at }) => ({
        url: '/api/planning/event',
        method: 'POST',
        params: { region_id: regionId, date },
        body: {
          type,
          ...(requestId != null ? { request_id: requestId } : {}),
          ...(engineerId != null ? { engineer_id: engineerId } : {}),
          ...(at != null ? { at } : {}),
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
  useApplyPlanEventMutation,
} = planningApi
