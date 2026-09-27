import { useState } from 'react'

import { AppModal, FieldLabel, RebuildLevelField, SegmentedControl, buttonClass } from '@/shared/ui'

import type { PlanDistribution, PlanRebuildLevel } from '../types'

const DISTRIBUTIONS: { id: PlanDistribution; label: string; hint: string }[] = [
  {
    id: 'even',
    label: 'Равномерное',
    hint: 'Заявки будут распределены равномерно между инженерами, максимальное количество зависит от квалификации инженера',
  },
  {
    id: 'efficient',
    label: 'Эффективное',
    hint: 'Заявки будут распределены максимально плотно между самыми эффективными и квалифицированными инженерами',
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
  const [distribution, setDistribution] = useState<PlanDistribution>('even')

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
