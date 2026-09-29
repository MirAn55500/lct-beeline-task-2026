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

/** Пометить день как «считается в фоне» — после upload, пока day-overview ещё не ответил. */
export function markPlanningDay(regionId: number, date: string) {
  planningDays.add(`${regionId}:${date}`)
}

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
      providesTags: (_result, _error, arg) => [
        'Plan',
        { type: 'Plan', id: `${arg.regionId}:${arg.date}` },
      ],
      // Фоновый расчёт после загрузки закончился — обновить план, карту, Гант и заявки
      async onQueryStarted(args, { dispatch, getCacheEntry, queryFulfilled }) {
        const day = `${args.regionId}:${args.date}`
        const prev = getCacheEntry().data
        if (prev?.planning) planningDays.add(day)
        try {
          const { data } = await queryFulfilled
          if (data.planning) {
            planningDays.add(day)
            return
          }
          const finishedPlanning = planningDays.delete(day)
          const planAppeared =
            Boolean(data.has_plan && data.plan_id) &&
            (!prev?.has_plan || prev.plan_id !== data.plan_id)
          // PlanExport — отдельно: иначе invalidate 'Plan' снова дергает day-overview.
          if (finishedPlanning || planAppeared) {
            dispatch(
              baseApi.util.invalidateTags([
                'PlanExport',
                { type: 'PlanExport', id: day },
                'Ticket',
              ]),
            )
          }
          if (!finishedPlanning) return
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
      invalidatesTags: (_result, _error, arg) => [
        'Plan',
        'PlanExport',
        'Ticket',
        { type: 'Plan', id: `${arg.regionId}:${arg.date}` },
        { type: 'PlanExport', id: `${arg.regionId}:${arg.date}` },
      ],
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
      invalidatesTags: (_result, _error, arg) => [
        'Plan',
        'PlanExport',
        'Ticket',
        { type: 'Plan', id: `${arg.regionId}:${arg.date}` },
        { type: 'PlanExport', id: `${arg.regionId}:${arg.date}` },
      ],
    }),
  }),
})

export const {
  useGetDayOverviewQuery,
  useGetPlanningHealthQuery,
  useRecalculatePlanMutation,
  useApplyPlanEventMutation,
} = planningApi
