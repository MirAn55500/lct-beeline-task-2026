import { useState } from 'react'

import { AppModal, buttonClass } from '@/shared/ui'

import type { PlanComparison, PlanEventResult } from '../types'

const CRITERION =
  'Сначала больше заявок, затем меньше инженеров, затем время в пути, затем километры. Если заявок стало больше, суммарный пробег может вырасти — смотрите километры на заявку.'

export function PlanCompareDialog({
  comparison,
  onClose,
}: {
  comparison: PlanComparison | null
  onClose: () => void
}) {
  return (
    <AppModal
      isOpen={comparison != null}
      onClose={onClose}
      title="Сравнение с базовым вариантом"
      description={comparison?.summary}
      footer={
        <button type="button" onClick={onClose} className={buttonClass.primary}>
          Понятно
        </button>
      }
    >
      <p className="text-xs leading-5 text-muted">{CRITERION}</p>
      {comparison ? (
        <ul className="mt-3 flex flex-col gap-2">
          {comparison.lines.map((line) => (
            <li key={line.label} className="flex flex-col text-sm leading-5">
              <span className="font-medium text-foreground">{line.label}</span>
              <span className="text-muted">
                {line.optimized} против {line.baseline} базового — {line.verdict}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </AppModal>
  )
}

export function UnavailableDialog({
  engineerId,
  onClose,
  onConfirm,
}: {
  engineerId: string | null
  onClose: () => void
  onConfirm: (at: string) => void
}) {
  const [at, setAt] = useState('12:00')
  return (
    <AppModal
      isOpen={engineerId != null}
      onClose={onClose}
      title="Инженер недоступен"
      description="Смена обрежется с этого времени. Уже начатые работы останутся в маршруте."
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass.outline}>
            Отмена
          </button>
          <button
            type="button"
            className={buttonClass.primary}
            onClick={() => onConfirm(at)}
          >
            Пересчитать остаток дня
          </button>
        </>
      }
    >
      <label className="flex flex-col gap-1 text-sm leading-5 text-foreground">
        Недоступен с
        <input
          type="time"
          value={at}
          onChange={(event) => setAt(event.target.value)}
          className="h-9 border border-border bg-surface px-3 text-sm outline-none focus:border-focus"
        />
      </label>
    </AppModal>
  )
}

export function PlanEventReport({
  result,
  onClose,
}: {
  result: PlanEventResult | null
  onClose: () => void
}) {
  const notes = result?.warnings.filter(Boolean) ?? []
  return (
    <AppModal
      isOpen={result != null}
      onClose={onClose}
      title="Что изменилось"
      description={result?.summary}
      footer={
        <button type="button" onClick={onClose} className={buttonClass.primary}>
          Понятно
        </button>
      }
    >
      {notes.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {notes.map((note) => (
            <li key={note} className="text-sm leading-5 text-muted">
              {note}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm leading-5 text-muted">
          Назначено {result?.assigned ?? 0}, без инженера: {result?.unassigned ?? 0}
        </p>
      )}
    </AppModal>
  )
}
