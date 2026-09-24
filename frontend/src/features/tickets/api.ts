import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

export type TicketAssignment = 'all' | 'assigned' | 'unassigned'

export type Ticket = {
  id: number
  number: string
  category: string
  reason: string | null
  reason_hint?: string | null
  engineer: string | null
  assigned: boolean
  window: string
  window_start: string
  window_end: string
  address: string
  status?: string | null
  hd?: string | null
  district?: string | null
}

export type TicketsListArgs = {
  regionId: number
  date: string
  planId?: number | null
  assignment?: TicketAssignment
  q?: string
  workTypes?: string[]
  reasons?: string[]
  timeFrom?: string | null
  timeTo?: string | null
}

export type UploadTicketsResult = {
  created: number
  updated: number
  skipped: number
  date: string | null
  plan_id: number | null
  plan_version: number | null
}

export const ticketsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getTicketsHealth: build.query<ModuleHealth, void>({
      query: () => '/api/tickets/health',
    }),
    getTickets: build.query<Ticket[], TicketsListArgs>({
      query: ({
        regionId,
        date,
        planId,
        assignment = 'all',
        q,
        workTypes = [],
        reasons = [],
        timeFrom,
        timeTo,
      }) => {
        const params = new URLSearchParams()
        params.set('region_id', String(regionId))
        params.set('date', date)
        if (planId != null) params.set('plan_id', String(planId))
        if (assignment !== 'all') params.set('assignment', assignment)
        if (q) params.set('q', q)
        for (const workType of workTypes) params.append('work_type', workType)
        for (const reason of reasons) params.append('reason', reason)
        if (timeFrom) params.set('time_from', timeFrom)
        if (timeTo) params.set('time_to', timeTo)
        return `/api/tickets?${params.toString()}`
      },
      providesTags: ['Ticket'],
    }),
    uploadTickets: build.mutation<UploadTicketsResult, FormData>({
      query: (body) => ({
        url: '/api/tickets/upload',
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Ticket', 'Plan'],
    }),
  }),
})

export const {
  useGetTicketsHealthQuery,
  useGetTicketsQuery,
  useLazyGetTicketsQuery,
  useUploadTicketsMutation,
} = ticketsApi
