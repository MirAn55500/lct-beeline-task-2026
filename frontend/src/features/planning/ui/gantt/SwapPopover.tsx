import { useLayoutEffect, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'

import type { GanttTask } from '../../ganttTypes'

const WIDTH = 369
const GAP = 8
// Примерная высота — чтобы решить, открывать вниз или вверх.
const POPOVER_HEIGHT = 160

type SwapPopoverProps = {
  /** Карточка «Не назначена», под которой висит поповер. */
  anchorTaskId: string
  displaced: GanttTask[]
  /** Лента прокручивается — поповер едет за карточкой. */
  scrollRef: RefObject<HTMLDivElement | null>
  onConfirm: () => void
  onCancel: () => void
}

/** «Подтвердите изменения» — замена назначенной заявки меняет маршрут, как Popover в макете. */
export function SwapPopover({ anchorTaskId, displaced, scrollRef, onConfirm, onCancel }: SwapPopoverProps) {
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    const scroller = scrollRef.current
    const update = () => {
      const anchor = document.querySelector<HTMLElement>(`[data-task-id="${CSS.escape(anchorTaskId)}"]`)
      if (!anchor) return setPosition(null)
      const rect = anchor.getBoundingClientRect()
      // По макету правый край совпадает с карточкой; снизу мало места — открываем вверх.
      const below = rect.bottom + GAP + POPOVER_HEIGHT < window.innerHeight
      setPosition({
        top: below ? rect.bottom + GAP : rect.top - GAP - POPOVER_HEIGHT,
        left: Math.max(16, Math.min(rect.right - WIDTH, window.innerWidth - WIDTH - 16)),
      })
    }
    update()
    scroller?.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      scroller?.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [anchorTaskId, scrollRef])

  if (!position) return null

  const numbers = displaced.map((task) => `№${task.id}`).join(', ')

  return createPortal(
    <div
      role="dialog"
      aria-label="Подтвердите изменения"
      className="fixed z-50 flex flex-col gap-2 bg-surface px-3 pt-2 pb-3"
      style={{
        top: position.top,
        left: position.left,
        width: WIDTH,
        borderRadius: 8,
        boxShadow:
          '0 14px 28px rgb(0 0 0 / 0.08), 0 -6px 12px rgb(0 0 0 / 0.03), 0 2px 8px rgb(0 0 0 / 0.06)',
      }}
    >
      <p className="text-sm leading-5 font-medium text-foreground">Подтвердите изменения</p>
      <p className="text-sm leading-5 text-foreground">
        Вы действительно хотите заменить задачу? Это повлияет на общий график работ
      </p>
      <p className="text-xs leading-4 text-muted">
        {displaced.length > 1 ? `Заявки ${numbers} уйдут` : `Заявка ${numbers} уйдёт`} в неназначенные —
        потребуется согласовать с клиентом новое время.
      </p>
      <div className="flex gap-1 pt-1">
        <button
          type="button"
          onClick={onConfirm}
          className="h-8 cursor-pointer bg-accent px-3 text-sm leading-5 font-medium text-accent-foreground transition-colors hover:bg-accent-hover"
          style={{ borderRadius: 8 }}
        >
          Подтвердить и заменить
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-8 cursor-pointer border border-border bg-surface px-3 text-sm leading-5 font-medium text-foreground transition-colors hover:bg-surface-hover"
          style={{ borderRadius: 8 }}
        >
          Отменить
        </button>
      </div>
    </div>,
    document.body,
  )
}
