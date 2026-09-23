import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

import type { Engineer } from './types'

export const personnelApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getPersonnelHealth: build.query<ModuleHealth, void>({
      query: () => '/api/personnel/health',
    }),
    getEngineers: build.query<Engineer[], number>({
      query: (regionId) => ({
        url: '/api/personnel/engineers',
        params: { region_id: regionId },
      }),
      providesTags: (_result, _error, regionId) => [
        { type: 'Engineer', id: regionId },
      ],
    }),
  }),
})

export const { useGetEngineersQuery, useGetPersonnelHealthQuery } = personnelApi
