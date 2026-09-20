import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

export const catalogsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getCatalogsHealth: build.query<ModuleHealth, void>({
      query: () => '/api/catalogs/health',
    }),
  }),
})

export const { useGetCatalogsHealthQuery } = catalogsApi
