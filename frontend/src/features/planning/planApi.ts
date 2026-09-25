import { baseApi } from '@/shared/api/baseApi'

import type { PlanExport } from './mocks'

/** План дня с расписанием визитов из backend — та же форма, что у выгрузки планировщика в моках. */
export type PlanExportResponse = PlanExport & { planId: number; version: number }

export const planExportApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getPlanExport: build.query<PlanExportResponse, { regionId: number; date: string; planId?: number | null }>({
      query: ({ regionId, date, planId }) => ({
        url: '/api/planning/plan',
        params: { region_id: regionId, date, ...(planId != null ? { plan_id: planId } : {}) },
      }),
      providesTags: ['Plan'],
    }),
  }),
})

export const { useGetPlanExportQuery } = planExportApi
