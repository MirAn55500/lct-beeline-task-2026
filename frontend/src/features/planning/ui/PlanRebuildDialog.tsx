import { useEffect, useState } from 'react'

import { AppModal, FieldLabel, RebuildLevelField, SegmentedControl, buttonClass } from '@/shared/ui'

import type { PlanDistribution, PlanRebuildLevel } from '../types'

const DISTRIBUTIONS: { id: PlanDistribution; label: string; hint: string }[] = [
  {
    id: 'even',
    label: 'Базовое',
    hint: 'Заявки берутся в порядке поступления и достаются первому подходящему инженеру по списку — всегда в конец маршрута. Адреса инженер посещает в порядке назначения.',
  },
  {
    id: 'efficient',
    label: 'Эффективное',
    hint: 'Заявки распределяются так, чтобы закрыть как можно больше заявок, аварийные — в первую очередь, минимальным числом инженеров и с наименьшими временем в пути и расстоянием.',
  },
]

type PlanRebuildDialogProps = {
  isOpen: boolean
  onClose: () => void
  onConfirm: (options: { level: PlanRebuildLevel; distribution: PlanDistribution }) => void
}

/** Modal «Обновить план»: насколько можно ломать текущий план и как делить заявки. */
export function PlanRebuildDialog({ isOpen, onClose, onConfirm }: PlanRebuildDialogProps) {
  const [level, setLevel] = useState<PlanRebuildLevel>('fix')
  const [distribution, setDistribution] = useState<PlanDistribution>('efficient')

  useEffect(() => {
    if (!isOpen) return
    setLevel('fix')
    setDistribution('efficient')
  }, [isOpen])

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title="Обновить план"
      description="Выберите вариант расчета и степень изменения уже сформированных планов"
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass.outline}>
            Отмена
          </button>
          <button
            type="button"
            onClick={() => {
              onClose()
              onConfirm({ level, distribution })
            }}
            className={buttonClass.primary}
          >
            Обновить план
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <RebuildLevelField value={level} onChange={setLevel} />
        <div className="flex flex-col gap-1">
          <FieldLabel>Распределение заявок</FieldLabel>
          <SegmentedControl
            aria-label="Распределение заявок"
            options={DISTRIBUTIONS}
            value={distribution}
            onChange={setDistribution}
          />
          <p className="text-xs leading-5 text-muted">
            {DISTRIBUTIONS.find((item) => item.id === distribution)?.hint}
          </p>
        </div>
      </div>
    </AppModal>
  )
}
