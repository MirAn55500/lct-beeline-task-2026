import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react'

import { env } from '@/shared/config/env'
import { apiTagTypes } from '@/shared/api/tags'

/**
 * Единый API-клиент. Эндпоинты добавляются через injectEndpoints
 * в файлах features/<feature>/api.ts
 */
export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery: fetchBaseQuery({
    baseUrl: env.apiBaseUrl,
  }),
  tagTypes: [...apiTagTypes],
  endpoints: () => ({}),
})
