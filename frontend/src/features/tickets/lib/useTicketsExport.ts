import { toast } from '@heroui/react'

import { useLazyGetTicketsQuery } from '../api'
import { downloadTickets, mockTickets } from './exportTickets'

/** «Экспорт csv / json» из меню «Заявки»: все заявки дня одним файлом. Версия плана не обязательна. */
export function useTicketsExport() {
  const [loadTickets] = useLazyGetTicketsQuery()

  return async (
    args: { regionId: number; date: string; planId: number | null; offline?: boolean },
    format: 'csv' | 'json',
    fileName: string,
  ) => {
    try {
      const tickets = args.offline
        ? mockTickets(args.regionId, args.date)
        : await loadTickets(args).unwrap()
      downloadTickets(tickets, format, fileName)
    } catch {
      toast.danger('Не удалось выгрузить заявки')
    }
  }
}
