import { useEffect, useRef, type ComponentProps, type ReactNode } from 'react'
import { TimeField } from '@heroui/react'
import type { Time } from '@internationalized/date'
import { RiTimeLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

/** Поля форм страницы «Персонал»: добавление инженера и карточка бригады. */

export function FieldLabel({ children, required }: { children: ReactNode; required?: boolean }) {
  return (
    <span className="text-sm font-medium leading-6 text-foreground">
      {children}
      {required ? <span className="ms-1 text-danger">*</span> : null}
    </span>
  )
}

export function Hint({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-5 text-muted">{children}</p>
}

export function ToggleChip({
  active,
  onToggle,
  className,
  children,
}: {
  active: boolean
  onToggle: () => void
  className?: string
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      className={cn(
        'inline-flex h-7 cursor-pointer items-center gap-1 px-3 text-sm font-medium leading-5 transition-colors',
        active
          ? 'bg-accent text-accent-foreground hover:bg-accent-hover'
          : 'bg-surface-tertiary text-foreground hover:bg-default-hover',
        className,
      )}
      style={{ borderRadius: 8 }}
    >
      {children}
    </button>
  )
}

export function TextInput({
  value,
  onChange,
  placeholder,
  maxLength,
  'aria-label': ariaLabel,
}: {
  value: string
  onChange: (next: string) => void
  placeholder: string
  /** Столько же, сколько принимает backend, — иначе ошибка при сохранении. */
  maxLength?: number
  'aria-label': string
}) {
  return (
    <input
      type="text"
      aria-label={ariaLabel}
      maxLength={maxLength}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="h-9 w-full border border-border bg-surface px-3 text-sm leading-5 text-foreground outline-none placeholder:text-muted focus-visible:border-focus"
      style={{ borderRadius: 8 }}
    />
  )
}

type DateSegment = ComponentProps<typeof TimeField.Segment>['segment']

/** Сегмент времени, который сообщает, стёрт ли он. */
function WatchedSegment({
  segment,
  onPlaceholder,
}: {
  segment: DateSegment
  onPlaceholder: (type: string, placeholder: boolean) => void
}) {
  useEffect(() => {
    onPlaceholder(segment.type, segment.isPlaceholder)
  }, [segment.type, segment.isPlaceholder, onPlaceholder])
  return <TimeField.Segment segment={segment} />
}

/**
 * Время смены. Если стереть часы или минуты, TimeField держит последнее полное значение,
 * а в поле видно «––:00» — такое время молча ушло бы на сервер. Поэтому стёртый сегмент
 * — это «время не задано» (null), и форма не даст сохранить.
 */
export function WorkTimeField({
  value,
  onChange,
  'aria-label': ariaLabel,
}: {
  value: Time | null
  onChange: (next: Time | null) => void
  'aria-label': string
}) {
  const cleared = useRef(new Set<string>())
  const changeRef = useRef(onChange)
  const valueRef = useRef(value)
  useEffect(() => {
    changeRef.current = onChange
    valueRef.current = value
  })
  const onPlaceholder = useRef((type: string, placeholder: boolean) => {
    if (type !== 'hour' && type !== 'minute') return
    if (placeholder) cleared.current.add(type)
    else cleared.current.delete(type)
    if (cleared.current.size > 0 && valueRef.current != null) changeRef.current(null)
  }).current

  return (
    <TimeField
      aria-label={ariaLabel}
      hourCycle={24}
      value={value}
      onChange={onChange}
      className="min-w-0 flex-1"
    >
      <TimeField.Group
        className="flex h-9 w-full items-center border border-border bg-surface shadow-none"
        style={{ borderRadius: 8, paddingLeft: 12, paddingRight: 12 }}
      >
        <TimeField.Input className="min-w-0 flex-1 text-sm leading-5 text-foreground">
          {(segment) => <WatchedSegment segment={segment} onPlaceholder={onPlaceholder} />}
        </TimeField.Input>
        <TimeField.Suffix className="ms-2">
          <RiTimeLine size={16} className="text-muted" />
        </TimeField.Suffix>
      </TimeField.Group>
    </TimeField>
  )
}
