import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

export const planningApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getPlanningHealth: build.query<ModuleHealth, void>({
      query: () => '/api/planning/health',
    }),
  }),
})

export const { useGetPlanningHealthQuery } = planningApi
