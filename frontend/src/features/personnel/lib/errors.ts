/** Причина отказа сервера для тоста: текст ошибки backend или понятная замена. */
export function errorReason(error: unknown) {
  const detail = ((error as { data?: unknown } | null)?.data as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  // 422 FastAPI — список ошибок полей; форма их не допускает, так что это что-то вне формы
  if (Array.isArray(detail)) return 'Сервер не принял данные — проверьте поля формы'
  if ((error as { status?: unknown } | null)?.status === 'FETCH_ERROR')
    return 'Нет связи с сервером'
  return 'Что-то пошло не так'
}
