import { createElement, useState } from 'react'
import { toast } from '@heroui/react'

import { formatWait } from '@/shared/lib/format'
import { pluralRu } from '@/shared/lib/text'
import type { RebuildLevel } from '@/shared/ui'

import {
  useCreateTicketMutation,
  useUploadTicketsMutation,
  type CreateTicketBody,
  type CreateTicketResult,
  type UploadTicketsResult,
} from '../api'

type UploadArgs = {
  file: File
  regionId: number
  /** День, на который вешаются строки без даты, YYYY-MM-DD. */
  date: string
  /**
   * Уровень перестроения: Фикс и Инженерный ставят заявки в текущий план, Свободный
   * считает день заново. Без него — Свободный (перетаскивание файла на пустой день).
   */
  remakeLevel?: RebuildLevel
}

/** Текст ошибки backend: FastAPI кладёт его в detail. */
function errorReason(error: unknown, fallback = 'Проверьте формат файла и попробуйте снова') {
  const data = (error as { data?: unknown } | null)?.data
  const detail = (data as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) return fallback
  if ((error as { status?: unknown } | null)?.status === 'FETCH_ERROR') return 'Нет связи с сервером'
  return fallback
}

/** Что с планом после загрузки: он считается в фоне, готовность видно в шапке. */
function planningNote(seconds: number | null | undefined) {
  const wait = seconds != null ? ` — это ${formatWait(seconds)}` : ''
  return `План составляется${wait}, он обновится сам`
}

/**
 * Загрузка выгрузки заявок с тостами из макета: «Загрузка заявок завершена»
 * со счётчиками или «Не удалось завершить загрузку» с кнопкой «Повторить».
 */
export function useTicketsUpload(onUploaded?: (result: UploadTicketsResult) => void) {
  const [uploadTickets] = useUploadTicketsMutation()
  const [isUploading, setUploading] = useState(false)

  const upload = async (args: UploadArgs): Promise<boolean> => {
    const body = new FormData()
    body.append('file', args.file)
    body.append('region_id', String(args.regionId))
    body.append('date', args.date)
    if (args.remakeLevel) body.append('remake_level', args.remakeLevel)

    setUploading(true)
    try {
      const result = await uploadTickets(body).unwrap()
      const unchanged = result.created === 0 && result.updated === 0
      toast.success('Загрузка заявок завершена', {
        description:
          `Добавлено ${result.created} ${pluralRu(result.created, ['заявка', 'заявки', 'заявок'])}, обновлено: ${result.updated}` +
          (result.planning
            ? `. ${planningNote(result.planning_eta_seconds)}`
            : unchanged
              ? '. Изменений нет — план остался прежним'
              : ''),
      })
      if (result.warnings?.length) {
        // Строки с ошибками пропущены, неточные адреса — в плане по району: диспетчер должен это видеть
        toast.warning('Не всё из файла удалось взять', {
          description: createElement(
            'ul',
            { className: 'list-disc pl-4' },
            result.warnings.map((line) => createElement('li', { key: line }, line)),
          ),
          timeout: 0,
        })
      }
      onUploaded?.(result)
      return true
    } catch (error) {
      toast.danger('Не удалось завершить загрузку', {
        description: errorReason(error),
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => void upload(args),
        },
      })
      return false
    } finally {
      setUploading(false)
    }
  }

  return { upload, isUploading }
}

/**
 * «Добавить заявку»: одна заявка и её постановка в план дня. Ошибку (например, адрес
 * не нашёлся на карте) показываем тостом, а окно остаётся открытым — адрес можно поправить.
 */
export function useTicketCreate(onCreated?: (result: CreateTicketResult) => void) {
  const [createTicket, { isLoading: isCreating }] = useCreateTicketMutation()

  const create = async (body: CreateTicketBody): Promise<boolean> => {
    try {
      const result = await createTicket(body).unwrap()
      toast.success(`Заявка №${result.number} добавлена`, {
        description: result.planning ? planningNote(result.planning_eta_seconds) : undefined,
      })
      onCreated?.(result)
      return true
    } catch (error) {
      toast.danger('Заявка не добавлена', {
        description: errorReason(error, 'Проверьте поля заявки и попробуйте снова'),
      })
      return false
    }
  }

  return { create, isCreating }
}
