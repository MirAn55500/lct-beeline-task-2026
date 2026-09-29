import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'
import type { RebuildLevel } from '@/shared/ui'
import { markPlanningDay } from '@/features/planning/api'

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
  /** План на даты из файла считается в фоне — готовность в `planning` обзора дня. */
  planning: boolean
  /** Примерно сколько секунд считаться плану на `date`. */
  planning_eta_seconds?: number | null
  /** Пропущенные строки с ошибками и адреса без точной точки — первые несколько. */
  warnings?: string[]
}

/** Окно «Добавить заявку». Время — «ЧЧ:ММ», тип работ — из WORK_TYPE_OPTIONS. */
export type CreateTicketBody = {
  region_id: number
  date: string
  address: string
  /** Точка адреса из подсказки или с карты. */
  lat?: number
  lon?: number
  start: string
  end: string
  work_type: string
  remake_level: RebuildLevel
}

export type CreateTicketResult = UploadTicketsResult & { number: string }

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
      invalidatesTags: (_result, _error, body) => {
        const regionId = body.get('region_id')
        const date = body.get('date')
        const day =
          typeof regionId === 'string' && typeof date === 'string'
            ? `${regionId}:${date}`
            : null
        return [
          'Ticket',
          'Plan',
          'PlanExport',
          ...(day
            ? [
                { type: 'Plan' as const, id: day },
                { type: 'PlanExport' as const, id: day },
              ]
            : []),
        ]
      },
      async onQueryStarted(body, { queryFulfilled }) {
        try {
          const { data } = await queryFulfilled
          if (!data.planning) return
          const regionId = Number(body.get('region_id'))
          const date = body.get('date')
          if (Number.isInteger(regionId) && regionId > 0 && typeof date === 'string') {
            markPlanningDay(regionId, date)
          }
        } catch {
          // тост покажет useTicketsUpload
        }
      },
    }),
    createTicket: build.mutation<CreateTicketResult, CreateTicketBody>({
      query: (body) => ({
        url: '/api/tickets',
        method: 'POST',
        body,
      }),
      invalidatesTags: (_result, _error, body) => [
        'Ticket',
        'Plan',
        'PlanExport',
        { type: 'Plan', id: `${body.region_id}:${body.date}` },
        { type: 'PlanExport', id: `${body.region_id}:${body.date}` },
      ],
      async onQueryStarted(body, { queryFulfilled }) {
        try {
          const { data } = await queryFulfilled
          if (!data.planning) return
          markPlanningDay(body.region_id, body.date)
        } catch {
          // тост покажет useTicketCreate
        }
      },
    }),
  }),
})

export const {
  useGetTicketsHealthQuery,
  useGetTicketsQuery,
  useLazyGetTicketsQuery,
  useUploadTicketsMutation,
  useCreateTicketMutation,
} = ticketsApi
