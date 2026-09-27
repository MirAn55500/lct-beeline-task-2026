import type { ReactNode } from 'react'

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

export { TextInput, WorkTimeField } from '@/shared/ui/formFields'
