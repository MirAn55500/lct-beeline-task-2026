/**
 * Конфиг из env (Vite: только VITE_*).
 * Пустой VITE_API_BASE_URL → относительные /api (через proxy в dev).
 */
export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '',
} as const
