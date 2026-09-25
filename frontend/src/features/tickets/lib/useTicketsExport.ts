import { toast } from '@heroui/react'

import { useLazyGetTicketsQuery } from '../api'
import { downloadTickets } from './exportTickets'

/** «Экспорт csv / json» из меню «Заявки»: все заявки дня выбранной версии плана одним файлом. */
export function useTicketsExport() {
  const [loadTickets] = useLazyGetTicketsQuery()

  return async (
    args: { regionId: number; date: string; planId: number | null },
    format: 'csv' | 'json',
    fileName: string,
  ) => {
    try {
      const tickets = await loadTickets(args).unwrap()
      downloadTickets(tickets, format, fileName)
    } catch {
      toast.danger('Не удалось выгрузить заявки')
    }
  }
}
