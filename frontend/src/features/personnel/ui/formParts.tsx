import type { ReactNode } from 'react'
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
  'aria-label': ariaLabel,
}: {
  value: string
  onChange: (next: string) => void
  placeholder: string
  'aria-label': string
}) {
  return (
    <input
      type="text"
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="h-9 w-full border border-border bg-surface px-3 text-sm leading-5 text-foreground outline-none placeholder:text-muted focus-visible:border-focus"
      style={{ borderRadius: 8 }}
    />
  )
}

export function WorkTimeField({
  value,
  onChange,
  'aria-label': ariaLabel,
}: {
  value: Time | null
  onChange: (next: Time | null) => void
  'aria-label': string
}) {
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
          {(segment) => <TimeField.Segment segment={segment} />}
        </TimeField.Input>
        <TimeField.Suffix className="ms-2">
          <RiTimeLine size={16} className="text-muted" />
        </TimeField.Suffix>
      </TimeField.Group>
    </TimeField>
  )
}
