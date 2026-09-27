import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

import type {
  AddressSuggestion,
  BrigadeArea,
  CreateEngineerBody,
  Engineer,
  EngineersListArgs,
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
  in_planning: boolean
  area_ids: number[]
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
  start_work?: string | null
  end_work?: string | null
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
    inPlanning: item.in_planning ?? true,
    areaIds: item.area_ids ?? [],
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
    qualification: (item.qualification as QualificationCode | null) ?? null,
    position: item.position,
    qualificationHint: item.qualification_hint,
    startWork: item.start_work,
    endWork: item.end_work,
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
  useDeleteEngineerMutation,
  useUpdateBrigadeMutation,
} = personnelApi
