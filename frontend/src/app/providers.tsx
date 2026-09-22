import type { ReactNode } from 'react'
import { I18nProvider } from '@heroui/react'
import { Provider } from 'react-redux'
import { BrowserRouter } from 'react-router'

import { store } from '@/app/store'

type AppProvidersProps = {
  children: ReactNode
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <Provider store={store}>
      <I18nProvider locale="ru-RU">
        <BrowserRouter>{children}</BrowserRouter>
      </I18nProvider>
    </Provider>
  )
}
