import { useEffect, useState } from 'react'
import { Modal, useOverlayState } from '@heroui/react'
import { RiCloseLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

import type { PlanDistribution, RemakeLevel } from '../types'

const REMAKE_OPTIONS: {
  value: RemakeLevel
  label: string
  hint: string
}[] = [
  {
    value: 'fix',
    label: 'Фикс',
    hint: 'Можно добавить новую заявку только в свободное окно',
  },
  {
    value: 'engineer',
    label: 'Инженерный',
    hint: 'Заявки можно менять только в рамках одного инженера',
  },
  {
    value: 'free',
    label: 'Свободный',
    hint: 'Обратите внимание! На этом уровне перестраивается весь план',
  },
]

const DISTRIBUTION_OPTIONS: {
  value: PlanDistribution
  label: string
  hint: string
}[] = [
  {
    value: 'even',
    label: 'Базовое',
    hint: 'Заявки берутся в порядке поступления и достаются первому подходящему инженеру по списку — всегда в конец маршрута. Адреса инженер посещает в порядке назначения.',
  },
  {
    value: 'efficient',
    label: 'Эффективное',
    hint: 'Заявки распределяются так, чтобы закрыть как можно больше заявок, аварийные — в первую очередь, минимальным числом инженеров и с наименьшими временем в пути и расстоянием.',
  },
]

function SegmentedControl<T extends string>({
  'aria-label': ariaLabel,
  value,
  options,
  onChange,
  disabled,
}: {
  'aria-label': string
  value: T
  options: { value: T; label: string }[]
  onChange: (next: T) => void
  disabled?: boolean
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="flex w-full gap-0.5 bg-surface-tertiary p-0.5"
      style={{ borderRadius: 10 }}
    >
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              'flex h-8 min-w-0 flex-1 cursor-pointer items-center justify-center px-2 text-sm font-medium leading-5 transition-colors',
              selected
                ? 'bg-surface text-foreground shadow-sm'
                : 'bg-transparent text-muted hover:text-foreground',
              'disabled:cursor-not-allowed disabled:opacity-40',
            )}
            style={{ borderRadius: 8 }}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

type RemakePlanModalProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  isSubmitting?: boolean
  onSubmit: (args: {
    remakeLevel: RemakeLevel
    distribution: PlanDistribution
  }) => Promise<void>
}

export function RemakePlanModal({
  isOpen,
  onOpenChange,
  isSubmitting = false,
  onSubmit,
}: RemakePlanModalProps) {
  const state = useOverlayState({
    isOpen,
    onOpenChange: (next) => {
      if (!next && isSubmitting) return
      onOpenChange(next)
    },
  })
  const [remakeLevel, setRemakeLevel] = useState<RemakeLevel>('fix')
  const [distribution, setDistribution] = useState<PlanDistribution>('efficient')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!isOpen) return
    setRemakeLevel('fix')
    setDistribution('efficient')
    setSubmitting(false)
  }, [isOpen])

  const busy = isSubmitting || submitting
  const remakeHint =
    REMAKE_OPTIONS.find((item) => item.value === remakeLevel)?.hint ?? ''
  const distributionHint =
    DISTRIBUTION_OPTIONS.find((item) => item.value === distribution)?.hint ?? ''

  const submit = async () => {
    if (busy) return
    setSubmitting(true)
    try {
      await onSubmit({ remakeLevel, distribution })
      onOpenChange(false)
    } catch {
      onOpenChange(false)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal state={state}>
      <Modal.Backdrop
        isDismissable={!busy}
        className="bg-backdrop"
        style={{ backdropFilter: 'blur(4px)' }}
      >
        <Modal.Container placement="center" className="p-4">
          <Modal.Dialog
            className="flex w-full max-w-[450px] flex-col overflow-hidden bg-surface outline-none"
            style={{ borderRadius: 16 }}
          >
            <Modal.Header className="relative flex flex-col gap-1 px-5 pt-5 pb-0">
              <Modal.Heading className="pr-10 text-xl font-semibold leading-7 text-foreground">
                Обновить план
              </Modal.Heading>
              <p className="pr-10 text-sm leading-6 text-muted">
                Выберите вариант расчета и степень изменения уже сформированных
                планов
              </p>
              <Modal.CloseTrigger
                aria-label="Закрыть"
                isDisabled={busy}
                className="absolute top-4 right-4 flex size-8 cursor-pointer items-center justify-center text-muted transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40"
                style={{ borderRadius: 8 }}
              >
                <RiCloseLine size={16} />
              </Modal.CloseTrigger>
            </Modal.Header>

            <Modal.Body className="flex flex-col gap-4 px-5 py-4">
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1">
                  <span className="text-sm font-medium leading-6 text-foreground">
                    Уровень перестроения плана
                  </span>
                  <span className="text-sm font-medium text-danger">*</span>
                </div>
                <SegmentedControl
                  aria-label="Уровень перестроения плана"
                  value={remakeLevel}
                  options={REMAKE_OPTIONS}
                  onChange={setRemakeLevel}
                  disabled={busy}
                />
                <p className="text-xs leading-5 text-muted">{remakeHint}</p>
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1">
                  <span className="text-sm font-medium leading-6 text-foreground">
                    Распределение заявок
                  </span>
                  <span className="text-sm font-medium text-danger">*</span>
                </div>
                <SegmentedControl
                  aria-label="Распределение заявок"
                  value={distribution}
                  options={DISTRIBUTION_OPTIONS}
                  onChange={setDistribution}
                  disabled={busy}
                />
                <p className="text-xs leading-5 text-muted">
                  {distributionHint}
                </p>
              </div>
            </Modal.Body>

            <Modal.Footer className="flex justify-end gap-3 px-5 pt-0 pb-5">
              <button
                type="button"
                disabled={busy}
                onClick={() => onOpenChange(false)}
                className="inline-flex h-9 cursor-pointer items-center justify-center border border-border bg-surface px-4 text-sm font-medium leading-5 text-foreground transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40"
                style={{ borderRadius: 8 }}
              >
                Отмена
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void submit()}
                className="inline-flex h-9 cursor-pointer items-center justify-center bg-accent px-4 text-sm font-medium leading-5 text-accent-foreground transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-accent/40"
                style={{ borderRadius: 8 }}
              >
                {busy ? 'Обновляем…' : 'Обновить план'}
              </button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  )
}
