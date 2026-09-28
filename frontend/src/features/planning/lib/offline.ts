/**
 * Backend не поднят: у ошибки RTK Query нет HTTP-статуса (FETCH_ERROR),
 * либо прокси отвечает 502/503/504, потому что процесс на :8000 не слушает.
 * Тогда страницы плана остаются на моках, а 404 и прочие ответы — это уже данные.
 */
const UNREACHABLE = new Set([502, 503, 504])

export function isOfflineError(isError: boolean, error: unknown) {
  if (!isError) return false
  const status = (error as { status?: unknown } | undefined)?.status
  if (typeof status !== 'number') return true
  return UNREACHABLE.has(status)
}
