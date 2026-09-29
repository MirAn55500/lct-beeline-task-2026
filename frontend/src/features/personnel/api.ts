import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

import type {
  AddressSuggestion,
  BrigadeArea,
  CreateEngineerBody,
  Engineer,
  EngineerBody,
  EngineersListArgs,
  LunchPlace,
  PersonnelBrigade,
  PersonnelEngineer,
  PersonnelFilterOptions,
  QualificationCode,
  SkillCode,
  TransportCode,
  UpdateBrigadeBody,
  UpdateBrigadeResult,
} from './types'

type ApiBrigade = {
  id: number
  name: string
  number: string
  region_id: number
  engineers_count: number
  leader_name: string | null
  leader_short_name: string | null
  office_address: string | null
  office_lat: number | null
  office_lon: number | null
  start_work: string | null
  end_work: string | null
  work_days: number[]
  area_ids: number[]
  lunch_start?: string | null
  lunch_end?: string | null
  lunch_place?: LunchPlace
  lunch_address?: string | null
  lunch_lat?: number | null
  lunch_lon?: number | null
}

type ApiUpdateBrigadeResult = ApiBrigade & {
  rescheduled_engineers: number
  office_moved: boolean
}

type ApiEngineer = {
  id: number
  name: string
  brigade_id: number
  brigade_name?: string | null
  transport: string
  transport_label: string
  skill: string | null
  skills: string[]
  skill_labels: string[]
  qualification?: string | null
  position?: string | null
  qualification_hint?: string | null
  is_lead: boolean
  planning_enabled: boolean
  start_work?: string | null
  end_work?: string | null
  own_schedule?: boolean
  work_days?: number[]
  own_work_days?: boolean
  lunch_start?: string | null
  lunch_end?: string | null
  own_lunch_time?: boolean
  lunch_place?: LunchPlace
  own_lunch_place?: boolean
  lunch_address?: string | null
  lunch_lat?: number | null
  lunch_lon?: number | null
  home_address?: string | null
}

function lunchPoint(item: { lunch_lat?: number | null; lunch_lon?: number | null }): [number, number] | null {
  return item.lunch_lat != null && item.lunch_lon != null ? [item.lunch_lon, item.lunch_lat] : null
}

type ApiUploadEngineersResult = {
  created: number
  skipped: number
  engineers: ApiEngineer[]
}

export type UploadEngineersResult = {
  created: number
  skipped: number
  engineers: PersonnelEngineer[]
}

function mapBrigade(item: ApiBrigade): PersonnelBrigade {
  return {
    id: item.id,
    name: item.name,
    number: item.number,
    regionId: item.region_id,
    engineersCount: item.engineers_count,
    leaderName: item.leader_name,
    leaderShortName: item.leader_short_name,
    officeAddress: item.office_address,
    officePoint:
      item.office_lat != null && item.office_lon != null ? [item.office_lon, item.office_lat] : null,
    startWork: item.start_work,
    endWork: item.end_work,
    workDays: item.work_days ?? [],
    areaIds: item.area_ids ?? [],
    lunchStart: item.lunch_start ?? null,
    lunchEnd: item.lunch_end ?? null,
    lunchPlace: item.lunch_place ?? 'last_request',
    lunchAddress: item.lunch_address ?? null,
    lunchPoint: lunchPoint(item),
  }
}

function mapPersonnelEngineer(item: ApiEngineer): PersonnelEngineer {
  return {
    id: item.id,
    brigadeId: item.brigade_id,
    brigadeName: item.brigade_name,
    name: item.name,
    skills: item.skills as SkillCode[],
    skillLabels: item.skill_labels,
    transport: item.transport as TransportCode,
    isLead: item.is_lead,
    planningEnabled: item.planning_enabled,
    qualification: (item.qualification as QualificationCode | null) ?? null,
    position: item.position,
    qualificationHint: item.qualification_hint,
    startWork: item.start_work,
    endWork: item.end_work,
    ownSchedule: item.own_schedule ?? false,
    workDays: item.work_days ?? [],
    ownWorkDays: item.own_work_days ?? false,
    lunchStart: item.lunch_start ?? null,
    lunchEnd: item.lunch_end ?? null,
    ownLunchTime: item.own_lunch_time ?? false,
    lunchPlace: item.lunch_place ?? 'last_request',
    ownLunchPlace: item.own_lunch_place ?? false,
    lunchAddress: item.lunch_address ?? null,
    lunchPoint: lunchPoint(item),
    homeAddress: item.home_address ?? null,
  }
}

function engineersQueryString(args: EngineersListArgs): string {
  const params = new URLSearchParams()
  if (args.regionId != null) params.set('region_id', String(args.regionId))
  if (args.brigadeId != null) params.set('brigade_id', String(args.brigadeId))
  if (args.q) params.set('q', args.q)
  for (const value of args.skills ?? []) params.append('skill', value)
  for (const value of args.transports ?? []) params.append('transport', value)
  for (const value of args.qualifications ?? []) params.append('qualification', value)
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const personnelApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getPersonnelHealth: build.query<ModuleHealth, void>({
      query: () => '/api/personnel/health',
    }),
    getPersonnelFilterOptions: build.query<PersonnelFilterOptions, void>({
      query: () => '/api/personnel/filter-options',
      providesTags: ['Engineer'],
    }),
    getBrigades: build.query<PersonnelBrigade[], number | void>({
      query: (regionId) => ({
        url: '/api/personnel/brigades',
        params: regionId != null ? { region_id: regionId } : undefined,
      }),
      transformResponse: (response: ApiBrigade[]) => response.map(mapBrigade),
      providesTags: ['Brigade'],
    }),
    getBrigadeAreas: build.query<BrigadeArea[], number>({
      query: (regionId) => ({ url: '/api/personnel/areas', params: { region_id: regionId } }),
      providesTags: ['Catalog'],
    }),
    /** Подсказки адресов для поля «Адрес офиса». */
    suggestAddress: build.query<AddressSuggestion[], string>({
      query: (q) => ({ url: '/api/personnel/address-suggest', params: { q } }),
      transformResponse: (
        response: { address: string; lat: number; lon: number; has_house: boolean }[],
      ) =>
        response.map((item) => ({
          address: item.address,
          lat: item.lat,
          lon: item.lon,
          hasHouse: item.has_house,
        })),
      keepUnusedDataFor: 300,
    }),
    /** Адрес точки, поставленной на карте. */
    reverseGeocode: build.query<
      { address: string | null; hasHouse: boolean },
      { lat: number; lon: number }
    >({
      query: ({ lat, lon }) => ({ url: '/api/personnel/reverse-geocode', params: { lat, lon } }),
      transformResponse: (response: { address: string | null; has_house: boolean }) => ({
        address: response.address,
        hasHouse: response.has_house,
      }),
    }),
    updateBrigade: build.mutation<UpdateBrigadeResult, { id: number; body: UpdateBrigadeBody }>({
      query: ({ id, body }) => ({ url: `/api/personnel/brigades/${id}`, method: 'PATCH', body }),
      transformResponse: (response: ApiUpdateBrigadeResult) => ({
        ...mapBrigade(response),
        rescheduledEngineers: response.rescheduled_engineers,
        officeMoved: response.office_moved,
      }),
      // Офис — старт маршрутов на карте плана, смены инженеров — в таблице и Ганте
      invalidatesTags: ['Brigade', 'Engineer', 'Plan'],
    }),
    /** Обзор дня: инженеры региона. */
    getEngineers: build.query<Engineer[], number>({
      query: (regionId) => ({
        url: '/api/personnel/engineers',
        params: { region_id: regionId },
      }),
      providesTags: (_result, _error, regionId) => [
        { type: 'Engineer', id: regionId },
      ],
    }),
    getPersonnelEngineers: build.query<PersonnelEngineer[], EngineersListArgs>({
      query: (args) => `/api/personnel/engineers${engineersQueryString(args)}`,
      transformResponse: (response: ApiEngineer[]) => response.map(mapPersonnelEngineer),
      providesTags: (result) =>
        result
          ? [
              ...result.map((item) => ({ type: 'Engineer' as const, id: item.id })),
              { type: 'Engineer', id: 'LIST' },
            ]
          : [{ type: 'Engineer', id: 'LIST' }],
    }),
    createEngineer: build.mutation<PersonnelEngineer, CreateEngineerBody>({
      query: (body) => ({
        url: '/api/personnel/engineers',
        method: 'POST',
        body,
      }),
      transformResponse: (response: ApiEngineer) => mapPersonnelEngineer(response),
      invalidatesTags: ['Engineer', 'Brigade'],
    }),
    uploadEngineers: build.mutation<
      UploadEngineersResult,
      { file: File; brigadeId: number }
    >({
      query: ({ file, brigadeId }) => {
        const body = new FormData()
        body.append('file', file)
        body.append('brigade_id', String(brigadeId))
        return { url: '/api/personnel/engineers/upload', method: 'POST', body }
      },
      transformResponse: (response: ApiUploadEngineersResult) => ({
        created: response.created,
        skipped: response.skipped,
        engineers: response.engineers.map(mapPersonnelEngineer),
      }),
      invalidatesTags: ['Engineer', 'Brigade'],
    }),
    updateEngineer: build.mutation<PersonnelEngineer, { id: number; body: EngineerBody }>({
      query: ({ id, body }) => ({ url: `/api/personnel/engineers/${id}`, method: 'PATCH', body }),
      transformResponse: (response: ApiEngineer) => mapPersonnelEngineer(response),
      // Бригада — счётчик и бригадир в списке; план — имена и смены на Ганте
      invalidatesTags: ['Engineer', 'Brigade', 'Plan'],
    }),
    updateEngineerPlanning: build.mutation<
      PersonnelEngineer,
      { id: number; planningEnabled: boolean }
    >({
      query: ({ id, planningEnabled }) => ({
        url: `/api/personnel/engineers/${id}/planning`,
        method: 'PATCH',
        body: { planning_enabled: planningEnabled },
      }),
      transformResponse: (response: ApiEngineer) => mapPersonnelEngineer(response),
      invalidatesTags: ['Engineer', 'Plan'],
    }),
    deleteEngineer: build.mutation<void, number>({
      query: (engineerId) => ({
        url: `/api/personnel/engineers/${engineerId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Engineer', 'Brigade'],
    }),
  }),
})

export const {
  useGetPersonnelHealthQuery,
  useGetPersonnelFilterOptionsQuery,
  useGetBrigadesQuery,
  useGetBrigadeAreasQuery,
  useLazyReverseGeocodeQuery,
  useLazySuggestAddressQuery,
  useGetEngineersQuery,
  useGetPersonnelEngineersQuery,
  useCreateEngineerMutation,
  useUploadEngineersMutation,
  useDeleteEngineerMutation,
  useUpdateEngineerPlanningMutation,
  useUpdateBrigadeMutation,
  useUpdateEngineerMutation,
} = personnelApi
