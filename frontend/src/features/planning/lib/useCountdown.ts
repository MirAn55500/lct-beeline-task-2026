import { useEffect, useState } from 'react'

/**
 * Обратный отсчёт от `seconds`, пока `active`: для индикатора «Обновить план»,
 * у которого нет фоновой очереди и сервер не сообщает остаток. Не уходит ниже нуля.
 */
export function useCountdown(active: boolean, seconds: number | null): number | null {
  const [left, setLeft] = useState<number | null>(null)

  useEffect(() => {
    if (!active || seconds == null) {
      setLeft(null)
      return
    }
    const started = Date.now()
    setLeft(seconds)
    const timer = window.setInterval(() => {
      setLeft(Math.max(0, seconds - Math.round((Date.now() - started) / 1000)))
    }, 1000)
    return () => window.clearInterval(timer)
    // Оценку берём на момент старта: сводка может обновиться посреди расчёта
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  return left
}
