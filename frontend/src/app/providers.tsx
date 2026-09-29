import type { ReactNode } from 'react'
import { I18nProvider, ToastProvider } from '@heroui/react'
import { Provider } from 'react-redux'

import { store } from '@/app/store'

type AppProvidersProps = {
  children: ReactNode
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <Provider store={store}>
      <I18nProvider locale="ru-RU">
        {children}
        <ToastProvider placement="bottom" />
      </I18nProvider>
    </Provider>
  )
}
