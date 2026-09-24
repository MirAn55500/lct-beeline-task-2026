import { baseApi } from '@/shared/api/baseApi'
import type { ModuleHealth } from '@/shared/types'

import type {
  CreateEngineerBody,
  Engineer,
  EngineersListArgs,
  PersonnelBrigade,
  PersonnelEngineer,
  PersonnelFilterOptions,
  QualificationCode,
  SkillCode,
  TransportCode,
} from './types'

type ApiBrigade = {
  id: number
  name: string
  number: string
  region_id: number
  engineers_count: number
  leader_name: string | null
  leader_short_name: string | null
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
  useGetEngineersQuery,
  useGetPersonnelEngineersQuery,
  useCreateEngineerMutation,
  useDeleteEngineerMutation,
} = personnelApi
