/**
 * Backend не поднят: у ошибки RTK Query нет HTTP-статуса (FETCH_ERROR и т. п.).
 * Тогда страницы плана остаются на моках, а 404 и прочие ответы — это уже данные.
 */
export function isOfflineError(isError: boolean, error: unknown) {
  return isError && typeof (error as { status?: unknown } | undefined)?.status !== 'number'
}
