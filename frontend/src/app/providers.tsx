import type { ReactNode } from 'react'
import { Provider } from 'react-redux'
import { BrowserRouter } from 'react-router'

import { store } from '@/app/store'

type AppProvidersProps = {
  children: ReactNode
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <Provider store={store}>
      <BrowserRouter>{children}</BrowserRouter>
    </Provider>
  )
}
