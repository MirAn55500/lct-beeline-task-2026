import { useState } from 'react'
import { toast } from '@heroui/react'

import { pluralRu } from '@/shared/lib/text'

import { useUploadTicketsMutation, type UploadTicketsResult } from '../api'

type UploadArgs = {
  file: File
  regionId: number
  /** День, на который вешаются строки без даты, YYYY-MM-DD. */
  date: string
}

/** Текст ошибки backend: FastAPI кладёт его в detail. */
function errorReason(error: unknown) {
  const data = (error as { data?: unknown } | null)?.data
  const detail = (data as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) return 'Проверьте формат файла и попробуйте снова'
  if ((error as { status?: unknown } | null)?.status === 'FETCH_ERROR') return 'Нет связи с сервером'
  return 'Проверьте формат файла и попробуйте снова'
}

/**
 * Загрузка выгрузки заявок с тостами из макета: «Загрузка заявок завершена»
 * со счётчиками или «Не удалось завершить загрузку» с кнопкой «Повторить».
 */
export function useTicketsUpload(onUploaded?: (result: UploadTicketsResult) => void) {
  const [uploadTickets] = useUploadTicketsMutation()
  const [isUploading, setUploading] = useState(false)

  const upload = async ({ file, regionId, date }: UploadArgs): Promise<boolean> => {
    const body = new FormData()
    body.append('file', file)
    body.append('region_id', String(regionId))
    body.append('date', date)

    setUploading(true)
    try {
      const result = await uploadTickets(body).unwrap()
      toast.success('Загрузка заявок завершена', {
        description: `Добавлено ${result.created} ${pluralRu(result.created, ['заявка', 'заявки', 'заявок'])}, обновлено: ${result.updated}`,
      })
      onUploaded?.(result)
      return true
    } catch (error) {
      toast.danger('Не удалось завершить загрузку', {
        description: errorReason(error),
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => void upload({ file, regionId, date }),
        },
      })
      return false
    } finally {
      setUploading(false)
    }
  }

  return { upload, isUploading }
}
