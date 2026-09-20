import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

export const personnelApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getPersonnelHealth: build.query<ModuleHealth, void>({
      query: () => '/api/personnel/health',
    }),
  }),
})

export const { useGetPersonnelHealthQuery } = personnelApi
