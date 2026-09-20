import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

export const ticketsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getTicketsHealth: build.query<ModuleHealth, void>({
      query: () => '/api/tickets/health',
    }),
  }),
})

export const { useGetTicketsHealthQuery } = ticketsApi
