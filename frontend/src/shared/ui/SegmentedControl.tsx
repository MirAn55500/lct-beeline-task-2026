import { Fragment, type ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'
import { segmentClass } from '@/shared/ui/buttonStyles'

export type SegmentedOption<T extends string> = {
  id: T
  label: ReactNode
}

type SegmentedControlProps<T extends string> = {
  options: SegmentedOption<T>[]
  value: T
  /** Без onChange сегменты рисует renderOption — например, как ссылки. */
  onChange?: (value: T) => void
  renderOption?: (option: SegmentedOption<T>, props: SegmentProps) => ReactNode
  'aria-label': string
  className?: string
}

export type SegmentProps = {
  active: boolean
  className: string
}

/**
 * Переключатель вида (Гант/Карта), вкладок бригады и режимов пересчёта —
 * везде один компонент Tabs из макета, поэтому и здесь один.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  renderOption,
  className,
  'aria-label': ariaLabel,
}: SegmentedControlProps<T>) {
  const activeIndex = options.findIndex((option) => option.id === value)

  return (
    <div
      role={renderOption ? undefined : 'tablist'}
      aria-label={ariaLabel}
      className={cn('flex h-9 items-center gap-0.5 rounded-[8px] bg-[#ebebec] px-1.5 py-0.5', className)}
    >
      {options.map((option, index) => {
        const active = option.id === value
        // Черта между двумя невыбранными сегментами; рядом с выбранным её не видно.
        const divider =
          index > 0 && index !== activeIndex && index - 1 !== activeIndex ? (
            <span aria-hidden className="h-5 w-px shrink-0 bg-[#18181b]/[0.06]" />
          ) : index > 0 ? (
            <span aria-hidden className="h-5 w-px shrink-0" />
          ) : null
        const props = { active, className: segmentClass(active) }

        return (
          <Fragment key={option.id}>
            {divider}
            {renderOption ? (
              renderOption(option, props)
            ) : (
              <button
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => onChange?.(option.id)}
                className={props.className}
              >
                {option.label}
              </button>
            )}
          </Fragment>
        )
      })}
    </div>
  )
}
