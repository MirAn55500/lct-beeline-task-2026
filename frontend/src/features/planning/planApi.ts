import { baseApi } from '@/shared/api/baseApi'

import type { PlanExport } from './mocks'

/** План дня с расписанием визитов из backend — та же форма, что у выгрузки планировщика в моках. */
export type PlanExportResponse = PlanExport & { planId: number; version: number }

/** Окно постановки: [позиция в маршруте, начать не раньше, не позже, выезд, минут в пути] — минуты дня. */
export type PlanSlot = [number, number, number, number, number]

export type PlanRequestSlots = {
  requestId: string
  movable: boolean
  /** Почему заявку не двигают (инженер уже выехал). */
  reason: string
  /** engineerId → окна постановки по позициям маршрута. */
  slots: Record<string, PlanSlot[]>
  /** engineerId → почему к этому инженеру нельзя. */
  refusals: Record<string, string>
}

export type PlanSlotsResponse = { planId: number; requests: PlanRequestSlots[] }

export type PlanMoveArgs = {
  planId: number
  requestId: string
  /** null — снять с маршрута. */
  engineerId: string | null
  /** Начало работ, минуты от полуночи дня плана. */
  start?: number
  /** Место в маршруте с 0; без него backend встанет по времени. */
  position?: number
  /** Снять с маршрутов, чтобы освободить место. */
  release?: string[]
  /** false — проверка с превью, true — новая версия плана. */
  commit?: boolean
}

export type PlanMoveVisit = {
  requestId: string
  engineerId: string
  position: number
  departure: number
  arrival: number
  start: number
  end: number
  travelMinutes: number
}

/** Обед после хода: заявку поставили на его время — обед уехал сам. */
export type PlanMoveLunch = {
  engineerId: string
  afterPosition: number
  departure: number
  arrival: number
  start: number
  end: number
}

export type PlanMoveResponse = {
  ok: boolean
  reason: string
  outsideWindow: boolean
  /** На сколько минут переехало окно клиента: согласованное время — новое окно той же длины. */
  windowShift: number
  /** Инженеры, чьи маршруты изменились. */
  engineers: string[]
  visits: PlanMoveVisit[]
  released: string[]
  /** Обеды изменившихся маршрутов; инженер из `engineers` без обеда здесь — обеда нет. */
  lunches?: PlanMoveLunch[]
  /** Сохранённая версия плана — только при commit. */
  planId: number | null
  version: number | null
}

export const planExportApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getPlanExport: build.query<PlanExportResponse, { regionId: number; date: string; planId?: number | null }>({
      query: ({ regionId, date, planId }) => ({
        url: '/api/planning/plan',
        params: { region_id: regionId, date, ...(planId != null ? { plan_id: planId } : {}) },
      }),
      providesTags: ['Plan'],
    }),
    // Версия плана не меняется — ход создаёт новую, поэтому окна не инвалидируются по тегу.
    getPlanSlots: build.query<PlanSlotsResponse, number>({
      query: (planId) => `/api/planning/plan/${planId}/slots`,
    }),
    movePlanRequest: build.mutation<PlanMoveResponse, PlanMoveArgs>({
      query: ({ planId, ...body }) => ({ url: `/api/planning/plan/${planId}/move`, method: 'POST', body }),
      // Проверка план не меняет; сохранённый ход — новая версия в списке и на ленте.
      invalidatesTags: (result, _error, args) => (args.commit && result?.ok ? ['Plan'] : []),
    }),
  }),
})

export const { useGetPlanExportQuery, useGetPlanSlotsQuery, useMovePlanRequestMutation } = planExportApi
