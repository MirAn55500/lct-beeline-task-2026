import { useSyncExternalStore } from 'react'

/**
 * Левая колонка всех экранов (бренд, меню, списки, колонка инженеров Ганта):
 * по макетам 306px на 1280 и 346px с 1440. Классы и число держим рядом,
 * чтобы колонки на разных страницах не разъезжались.
 */
export const ASIDE_WIDTH_CLASS = 'w-[306px] min-[1440px]:w-[346px]'

const WIDE_QUERY = '(min-width: 1440px)'

function subscribe(onChange: () => void) {
  const query = window.matchMedia(WIDE_QUERY)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/** Ширина левой колонки в пикселях — для расчётов, где класс не подходит. */
export function useAsideWidth() {
  return useSyncExternalStore(
    subscribe,
    () => (window.matchMedia(WIDE_QUERY).matches ? 346 : 306),
    () => 346,
  )
}
