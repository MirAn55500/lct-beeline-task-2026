import { configureStore } from '@reduxjs/toolkit'

import { baseApi } from '@/shared/api/baseApi'

// Регистрация injectEndpoints (побочный эффект импорта).
import '@/features/catalogs/api'
import '@/features/personnel/api'
import '@/features/planning/api'
import '@/features/tickets/api'

export const store = configureStore({
  reducer: {
    [baseApi.reducerPath]: baseApi.reducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware().concat(baseApi.middleware),
})

export type AppStore = typeof store
export type RootState = ReturnType<AppStore['getState']>
export type AppDispatch = AppStore['dispatch']
