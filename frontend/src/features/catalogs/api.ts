import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

import type { Region } from './types'

export const catalogsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getCatalogsHealth: build.query<ModuleHealth, void>({
      query: () => '/api/catalogs/health',
    }),
    getRegions: build.query<Region[], void>({
      query: () => '/api/catalogs/regions',
      providesTags: ['Catalog'],
    }),
  }),
})

export const { useGetCatalogsHealthQuery, useGetRegionsQuery } = catalogsApi
