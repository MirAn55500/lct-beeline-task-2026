import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

export type UploadTicketsResult = {
  created: number
  updated: number
  skipped: number
}

export const ticketsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getTicketsHealth: build.query<ModuleHealth, void>({
      query: () => '/api/tickets/health',
    }),
    uploadTickets: build.mutation<UploadTicketsResult, FormData>({
      query: (body) => ({
        url: '/api/tickets/upload',
        method: 'POST',
        body,
      }),
    }),
  }),
})

export const { useGetTicketsHealthQuery, useUploadTicketsMutation } = ticketsApi
